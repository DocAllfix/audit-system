# ==============================================================================
# STRUCTURED EVIDENCE PARSER — Parser YAML → dict Python
# ==============================================================================
# Converte l'output grezzo del PROMPT UNIVERSALE ADATTIVO v2.1 in dict Python.
# Zero dipendenze da altri moduli del progetto (solo stdlib + pyyaml).
# Zero side effects (nessuna scrittura su disco).
# Graceful degradation se PyYAML non installato.
# ==============================================================================

import re
import json
from typing import Optional, Dict, Any, List, Tuple

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# Campi fissi dell'intestazione scheda documento (dal PROMPT UNIVERSALE)
_HEADER_DOC_KEYS = frozenset({
    'tipo', 'categoria', 'categorie_secondarie', 'titolo',
    'riferimento', 'data_doc', 'data_scadenza',
    'emesso_da', 'soggetto', 'norme_pertinenti', 'firme', 'note_audit'
})

# Campi da eliminare silenziosamente se il modello li produce (legacy o privacy)
_STRIP_KEYS = frozenset({
    'commessa',                        # eliminato dal sistema (FIX #4)
    'cf', 'codice_fiscale',            # consentito SOLO P.IVA azienda, mai CF persona fisica
    'data_nascita', 'luogo_nascita',   # privacy
    'residenza_privata', 'indirizzo_residenza',
    'numero_documento', 'documento_identita',
})

# Pattern privacy per stripping su valori foglia (post-parsing)
_CF_PATTERN = re.compile(r'\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b')
_NATO_PATTERN = re.compile(
    r'\bnat[oa]\s+(?:il|a)\s+[^\n;,]{1,60}',
    re.IGNORECASE
)
_DATA_NASCITA_PATTERN = re.compile(
    r'\b(?:data\s+di\s+nascita|nato\s+il)\s*[:\-]?\s*\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b',
    re.IGNORECASE
)

_PRIVACY_REDACTED = "[dato privacy rimosso]"


def _redact_privacy_value(value):
    """Applica stripper privacy a una foglia (str). Altri tipi tornano intatti."""
    if not isinstance(value, str):
        return value
    out = value
    out = _CF_PATTERN.sub(_PRIVACY_REDACTED, out)
    out = _DATA_NASCITA_PATTERN.sub(_PRIVACY_REDACTED, out)
    out = _NATO_PATTERN.sub(_PRIVACY_REDACTED, out)
    return out


# Termini che indicano estrazione superficiale ("sì / presente" al posto dei dati)
_SHALLOW_VALUES = frozenset({
    "si", "sì", "presente", "conforme", "rilasciato", "ok", "yes", "true"
})

# Chiavi tipicamente associate a liste strutturate critiche in Visura / DVR
_EXPECTED_LIST_KEYS = frozenset({
    "soa", "attestazioni_soa", "certificazioni", "certificazioni_iso",
    "albi", "iscrizioni_albi", "albo_gestori", "rating_legalita",
    "cariche_sociali", "soci", "partecipazioni",
    "dpi", "dpi_assegnati", "fattori_rischio", "formazione",
    "scope_1", "scope_2", "scope_3", "see", "enpi",
    "temi_materiali", "kpi_ambientali", "kpi_sociali",
})


def _soft_audit_warnings(result: Dict) -> List[str]:
    """
    FASE C: log soft di warnings non bloccanti.
    Cerca su schede Visura/DVR/ESG campi che contengono valori superficiali
    come 'sì'/'presente' invece di liste atomiche.
    Zero side effects sull'output. Serve a monitorare la qualita'.
    """
    warnings: List[str] = []
    try:
        for sezione in result.get("sezioni", []):
            for doc in sezione.get("documenti", []):
                tipo = str(doc.get("tipo", "")).lower()
                titolo = str(doc.get("titolo", ""))
                is_critical = any(key in tipo for key in (
                    "visura", "camerale", "dvr", "valutazione rischi",
                    "bilancio", "esg", "sostenibilita",
                    "analisi energetica", "iso 50001", "iso 14064"
                ))
                if not is_critical:
                    continue
                cluster = doc.get("cluster", {}) or {}
                for cname, cdata in cluster.items():
                    if not isinstance(cdata, dict):
                        continue
                    for k, v in cdata.items():
                        klow = str(k).lower()
                        vlow = str(v).strip().lower() if not isinstance(v, (list, dict)) else ""
                        if klow in _EXPECTED_LIST_KEYS and vlow in _SHALLOW_VALUES:
                            warnings.append(
                                f"[QUALITY WARN] {tipo or 'doc'} '{titolo}' — "
                                f"cluster '{cname}' campo '{k}' ha valore '{v}'. "
                                f"Atteso: lista atomica."
                            )
        for w in warnings:
            print(w)
    except Exception as e:
        print(f"[QUALITY WARN] soft audit fallito: {e}")
    return warnings


def _scrub_tree(node):
    """Applica _STRIP_KEYS e _redact_privacy_value ricorsivamente su dict/list."""
    if isinstance(node, dict):
        keys_to_drop = [k for k in node.keys()
                        if isinstance(k, str) and k.lower() in _STRIP_KEYS]
        for k in keys_to_drop:
            del node[k]
        for k, v in list(node.items()):
            if isinstance(v, (dict, list)):
                _scrub_tree(v)
            else:
                node[k] = _redact_privacy_value(v)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if isinstance(v, (dict, list)):
                _scrub_tree(v)
            else:
                node[i] = _redact_privacy_value(v)


# ==============================================================================
# HELPERS INTERNI
# ==============================================================================

def _safe_yaml_load(text: str) -> Any:
    """
    Parsa YAML con fallback silenzioso. Ritorna None su qualsiasi errore.
    Usa un Loader custom che non converte OFF/ON/YES/NO in booleani
    (in contesto audit questi sono abbreviazioni di tipo documento).
    """
    if not HAS_YAML or not text or not text.strip():
        return None
    try:
        # Loader custom: disabilita la risoluzione booleana YAML 1.1
        # che trasforma OFF→False, ON→True, YES→True, NO→False, etc.
        class _AuditLoader(yaml.SafeLoader):
            pass

        # Rimuovi il resolver dei booleani che interferisce con le abbreviazioni
        _AuditLoader.yaml_implicit_resolvers = {
            k: [(tag, regexp) for tag, regexp in resolvers
                if tag != 'tag:yaml.org,2002:bool']
            for k, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
        }

        return yaml.load(text, Loader=_AuditLoader)
    except Exception:
        return None


def _extract_yaml_blocks(text: str) -> List[Tuple[int, str]]:
    """
    Estrae tutti i blocchi ```yaml...``` (o ```json, o senza tag) dal testo.
    Ritorna lista di (posizione_inizio, contenuto_raw).

    Se i fence esistono, estrae anche le porzioni di testo TRA fence che
    contengono dati utili (es. `# ── DOC N ──` o `^tipo:` top-level).
    Questo evita che batch non-fenced tra batch fenced vengano persi.
    """
    # Accetta yaml, YAML, json, JSON, o nessun tag — il parser tenta comunque.
    # Supporta anche fence non chiusi (truncation): match fino a fine testo.
    pattern = re.compile(
        r'```(?:yaml|YAML|json|JSON)?\s*\n(.*?)(?:```|\Z)',
        re.DOTALL
    )
    matches = list(pattern.finditer(text))
    blocks: List[Tuple[int, str]] = [(m.start(), m.group(1)) for m in matches]

    if not blocks:
        return blocks

    # Recupera porzioni tra/attorno fence che contengono schede non fence-wrappate.
    # Separatori DOC o righe `^tipo:` top-level → sono schede reali.
    useful_signal = re.compile(
        r'(^[ \t]*#[ \t]*[─\-═–—*_=.·•]*[ \t]*(?:DOC|SCHEDA|DOCUMENTO)[ \t]+\d+'
        r'|^tipo[ \t]*:[ \t]*["\']?\S)',
        re.MULTILINE | re.IGNORECASE
    )

    gaps: List[Tuple[int, int]] = []
    prev_end = 0
    for m in matches:
        if m.start() > prev_end:
            gaps.append((prev_end, m.start()))
        prev_end = m.end()
    if prev_end < len(text):
        gaps.append((prev_end, len(text)))

    for gstart, gend in gaps:
        segment = text[gstart:gend]
        if useful_signal.search(segment):
            blocks.append((gstart, segment))

    blocks.sort(key=lambda t: t[0])
    return blocks


def _extract_section_headers(text: str) -> List[Tuple[int, str, str]]:
    """
    Trova tutti gli header di sezione nel testo.
    Pattern atteso: ## SEZIONE 08 · LEGALE/SOCIETARIA
                    o ## 08 · LEGALE/SOCIETARIA
    Ritorna lista di (posizione, id_sezione, nome_sezione).
    """
    pattern = re.compile(
        r'^#{1,3}\s*(?:SEZIONE\s+)?(\d{2})\s*[·•]\s*(.+?)\s*$',
        re.MULTILINE
    )
    return [(m.start(), m.group(1).strip(), m.group(2).strip())
            for m in pattern.finditer(text)]


def _parse_meta_block(raw_yaml: str) -> Dict:
    """
    Parsa il blocco META e ritorna il dict normalizzato.
    Garantisce sempre le chiavi: audit, azienda, indice, abbrev_aggiunte.
    """
    parsed = _safe_yaml_load(raw_yaml)
    if not isinstance(parsed, dict):
        return {"audit": {}, "azienda": {}, "indice": [], "abbrev_aggiunte": []}

    return {
        "audit":           parsed.get("audit", {}) or {},
        "azienda":         parsed.get("azienda", {}) or {},
        "indice":          parsed.get("indice", []) or [],
        "abbrev_aggiunte": parsed.get("abbrev_aggiunte", []) or [],
    }


def _parse_doc_block(raw_yaml: str) -> Dict:
    """
    Parsa un singolo blocco YAML documento.
    Separa i campi header fissi dai campi liberi (cluster).
    Tenta di recuperare i nomi dei cluster dai commenti YAML
    (pattern: # ── NOME CLUSTER ───).
    """
    parsed = _safe_yaml_load(raw_yaml)
    if not isinstance(parsed, dict) or not parsed:
        return {}

    # Separa header da campi cluster
    doc = {}
    extra_fields = {}
    for k, v in parsed.items():
        if k in _HEADER_DOC_KEYS:
            doc[k] = v
        else:
            extra_fields[k] = v

    # Tenta di recuperare nomi cluster dai commenti # ── NOME ─────
    # Il pattern separa il raw yaml in segmenti per cluster
    cluster_pattern = re.compile(r'^#\s*─+\s*(.+?)\s*─*\s*$', re.MULTILINE)
    cluster_names = cluster_pattern.findall(raw_yaml)
    cluster_segments = cluster_pattern.split(raw_yaml)

    clusters: Dict[str, Dict] = {}

    if cluster_names and len(cluster_segments) > 1:
        # cluster_segments[0] = testo prima del primo cluster (header doc)
        # cluster_segments[1] = nome primo cluster
        # cluster_segments[2] = contenuto primo cluster
        # cluster_segments[3] = nome secondo cluster ...
        for i, name in enumerate(cluster_names):
            segment_idx = (i * 2) + 2  # salto: preambolo + nome_1 + seg_1 + nome_2 + seg_2 ...
            # La split alternata produce: [pre, name1, seg1, name2, seg2, ...]
            # con findall i nomi sono già estratti; split produce [pre, seg1, seg2, ...]
            # Uso schema corretto: split produce [pre, name1_val, seg1, name2_val, seg2, ...]
            # PyRegex split con gruppi cattura include i separatori
            pass

        # Approccio più robusto: splitta il raw_yaml sui commenti cluster
        parts = cluster_pattern.split(raw_yaml)
        # parts = [preambolo, nome_1, contenuto_1, nome_2, contenuto_2, ...]
        if len(parts) >= 3:
            for idx in range(1, len(parts) - 1, 2):
                cname = parts[idx].strip()
                ccontent = parts[idx + 1] if idx + 1 < len(parts) else ""
                cluster_data = _safe_yaml_load(ccontent) or {}
                if isinstance(cluster_data, dict):
                    # Rimuovi campi header che potrebbero comparire nel cluster
                    cluster_data = {k: v for k, v in cluster_data.items()
                                    if k not in _HEADER_DOC_KEYS}
                    if cluster_data:
                        clusters[cname] = cluster_data

    # Se nessun cluster nominato trovato, raggruppa tutto in "Dati estratti"
    if not clusters and extra_fields:
        clusters["Dati estratti"] = extra_fields

    doc["cluster"] = clusters

    # Assicura presenza campi obbligatori con default
    doc.setdefault("tipo", "N/A")
    doc.setdefault("categoria", "18 · ALTRI")
    doc.setdefault("note_audit", "")
    doc.setdefault("norme_pertinenti", [])

    return doc


def _find_sezione_for_pos(pos: int, section_headers: List[Tuple[int, str, str]],
                           categoria: str) -> Tuple[str, str]:
    """
    Determina id e nome sezione per un documento.
    Prima tenta di leggerlo dal campo categoria,
    poi cerca l'header di sezione più vicino prima della posizione.
    """
    # Tenta da campo categoria (es. "08 · LEGALE/SOCIETARIA")
    cat_str = str(categoria or "")
    cat_match = re.match(r'^(\d{2})\s*[·•]\s*(.+)', cat_str)
    if cat_match:
        return cat_match.group(1).strip(), cat_match.group(2).strip()

    # Fallback: header di sezione più vicino precedente
    for hpos, hid, hnome in reversed(section_headers):
        if hpos < pos:
            return hid, hnome

    return "18", "ALTRI"


# ==============================================================================
# API PUBBLICA
# ==============================================================================

def _extract_markdown_tables(text: str) -> Tuple[str, Dict[str, List[List[str]]]]:
    """
    Estrae le tabelle Markdown dal testo YAML (il modello le inserisce come dati).
    Ritorna (testo_senza_tabelle, {placeholder: [[row], [row], ...]}).
    Le tabelle vengono sostituite con un placeholder YAML-safe.
    """
    table_pattern = re.compile(
        r'((?:[ \t]*\|.+\|\n?)+)',
        re.MULTILINE
    )
    tables = {}
    counter = [0]

    def replace_table(m):
        raw = m.group(1).strip()
        rows = []
        for line in raw.splitlines():
            line = line.strip()
            if not line or re.match(r'^\|[-:| ]+\|$', line):
                continue  # salta separatori
            cells = [c.strip() for c in line.strip('|').split('|')]
            rows.append(cells)
        key = f"_TABLE_{counter[0]}_"
        tables[key] = rows
        counter[0] += 1
        return f'{key}: "__table__"\n'

    clean = table_pattern.sub(replace_table, text)
    return clean, tables


# Pattern YAML malformato ricorrente prodotto dall'LLM:
#   fattore_durata_tM_tabella: lista_vuota: true
# (nested inline mapping non valido). Lo convertiamo in forma multilinea:
#   fattore_durata_tM_tabella:
#     lista_vuota: true
# Vincoli: entrambe le key devono essere bare word (no quote, no spazi),
# il primo ':' deve essere seguito da >=1 spazio. Cosi' non tocchiamo
# stringhe quotate come titolo: "Autorizzazione: progetto".
_NESTED_INLINE_RE = re.compile(
    r'^(?P<indent>[ \t]*)(?P<k1>[A-Za-z_][A-Za-z0-9_]*)[ \t]*:[ \t]+'
    r'(?P<k2>[A-Za-z_][A-Za-z0-9_]*)[ \t]*:[ \t]*(?P<val>.+?)[ \t]*$',
    re.MULTILINE
)

def _sanitize_nested_inline_mapping(text: str) -> str:
    """Converte 'key1: key2: value' in multilinea valida.
    Applica solo a righe intere (bare word), non tocca valori quotati."""
    def repl(m):
        ind = m.group('indent')
        return f"{ind}{m.group('k1')}:\n{ind}  {m.group('k2')}: {m.group('val')}"
    return _NESTED_INLINE_RE.sub(repl, text)


_ERR_LINE_RE = re.compile(r'line[ \t]+(\d+),[ \t]+column[ \t]+\d+')

def _parse_yaml_with_line_skip(text: str, max_skip: int = 5) -> Optional[Any]:
    """Tenta il parse YAML; se fallisce, individua la riga con errore e la
    rimuove, poi ritenta (fino a max_skip righe). Ritorna None se anche
    cosi' non si ottiene un dict utile. Silenzioso (ritorna None su ogni
    eccezione). Usato come recovery per output LLM parzialmente invalidi."""
    if not HAS_YAML or not text or not text.strip():
        return None

    class _AuditLoader(yaml.SafeLoader):
        pass
    _AuditLoader.yaml_implicit_resolvers = {
        k: [(tag, regexp) for tag, regexp in resolvers
            if tag != 'tag:yaml.org,2002:bool']
        for k, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    current = text
    bad_lines: List[int] = []
    for _ in range(max_skip + 1):
        try:
            return yaml.load(current, Loader=_AuditLoader)
        except yaml.YAMLError as e:
            msg = str(e)
            # Estrai TUTTE le posizioni di errore e prendi la PIU' AVANZATA
            # (quella che ferma veramente il parser — la prima segnala solo
            #  il contesto, "while parsing a block mapping").
            positions = _ERR_LINE_RE.findall(msg)
            if not positions:
                return None
            ln = max(int(p) for p in positions)
            lines = current.split('\n')
            if ln < 1 or ln > len(lines):
                return None
            bad_lines.append(ln)
            lines.pop(ln - 1)
            current = '\n'.join(lines)
        except Exception:
            return None
    return None


# Fallback regex per estrarre campi minimi da chunk che il parser YAML rifiuta.
# Se il documento e' irrecuperabile, almeno preserviamo intestazione e categoria
# per non perdere la scheda nel report finale.
_FIELD_EXTRACT_RE = {
    'tipo': re.compile(r'^tipo[ \t]*:[ \t]*"([^"\n]+)"', re.MULTILINE),
    'categoria': re.compile(r'^categoria[ \t]*:[ \t]*"([^"\n]+)"', re.MULTILINE),
    'titolo': re.compile(r'^titolo[ \t]*:[ \t]*"([^"\n]+)"', re.MULTILINE),
    'riferimento': re.compile(r'^riferimento[ \t]*:[ \t]*"([^"\n]+)"', re.MULTILINE),
    'data_doc': re.compile(r'^data_doc[ \t]*:[ \t]*([^\n#]+?)[ \t]*$', re.MULTILINE),
    'emesso_da': re.compile(r'^emesso_da[ \t]*:[ \t]*"([^"\n]+)"', re.MULTILINE),
    'soggetto': re.compile(r'^soggetto[ \t]*:[ \t]*"([^"\n]+)"', re.MULTILINE),
}

def _regex_fallback_extract(chunk: str) -> Optional[Dict]:
    """Estrae campi intestazione con regex quando YAML fallisce. Segna la
    scheda con note_audit che indica recovery parziale."""
    result: Dict[str, Any] = {}
    for key, rx in _FIELD_EXTRACT_RE.items():
        m = rx.search(chunk)
        if m:
            result[key] = m.group(1).strip()
    if 'tipo' not in result and 'categoria' not in result:
        return None
    return result


def _yaml_chunk_to_doc(chunk: str, tables: Dict) -> Optional[Dict]:
    """
    Parsa un singolo chunk YAML (un documento) in dict.
    Ricostruisce le tabelle Markdown come cluster.
    Gestisce campi con commenti inline (tipo: CNC # commento).
    Recovery in 3 livelli: normal parse → sanitizza nested → retry con line-skip
    → fallback regex su campi header.
    """
    # Rimuovi righe che sono solo commenti di sezione (# ── DOC N ──, # SEZIONE N)
    lines = []
    for line in chunk.splitlines():
        stripped = line.strip()
        # Tieni solo righe non-comment, o commenti inline (parte di un campo YAML)
        if stripped.startswith('#') and not re.match(r'^(\w)', stripped):
            continue  # commento standalone → scarta
        lines.append(line)
    clean_chunk = '\n'.join(lines)

    # Rimuovi commenti inline dal YAML (# testo dopo valore)
    clean_chunk = re.sub(r'(\S)\s+#[^"\']*$', r'\1', clean_chunk, flags=re.MULTILINE)

    # LIVELLO 1: parse diretto
    parsed = _safe_yaml_load(clean_chunk)

    # LIVELLO 2: sanitizza nested inline mapping + retry
    if not isinstance(parsed, dict):
        sanitized = _sanitize_nested_inline_mapping(clean_chunk)
        if sanitized != clean_chunk:
            parsed = _safe_yaml_load(sanitized)
        # LIVELLO 3: line-skip recovery (fino a 5 righe malformate)
        if not isinstance(parsed, dict):
            parsed = _parse_yaml_with_line_skip(sanitized if sanitized != clean_chunk else clean_chunk)

    # LIVELLO 4: fallback regex header-only
    if not isinstance(parsed, dict):
        fallback = _regex_fallback_extract(clean_chunk)
        if fallback is None:
            return None
        parsed = fallback
        parsed['note_audit'] = ("[RECOVERY] Scheda ricostruita da header-only; "
                                "corpo YAML malformato dal modello.")

    # Campi obbligatori minimi
    if "tipo" not in parsed and "categoria" not in parsed:
        return None

    # Separa i campi standard dai cluster liberi
    std_keys = _HEADER_DOC_KEYS
    cluster = {}
    doc = {}

    for k, v in parsed.items():
        if k.startswith('_TABLE_'):
            # Ricostruisci tabella Markdown
            tbl_data = tables.get(k, [])
            if tbl_data and len(tbl_data) >= 2:
                headers = tbl_data[0]
                rows = []
                for row in tbl_data[1:]:
                    rows.append({headers[i]: row[i] if i < len(row) else "" for i in range(len(headers))})
                cluster[k.strip('_0123456789').replace('TABLE', 'Tabella')] = rows
            elif tbl_data:
                cluster['Tabella'] = tbl_data
        elif k in std_keys:
            doc[k] = v
        else:
            cluster[k] = v

    doc['cluster'] = cluster
    # Garantisce presenza campi minimi (commessa rimossa — FIX #4)
    for field in ('tipo', 'categoria', 'categorie_secondarie', 'titolo',
                  'riferimento', 'data_doc', 'data_scadenza',
                  'emesso_da', 'soggetto', 'norme_pertinenti', 'firme', 'note_audit'):
        if field not in doc:
            doc[field] = [] if field in ('categorie_secondarie', 'norme_pertinenti') else ({} if field == 'firme' else "")
    return doc


def _split_into_meta_and_docs(yaml_content: str) -> Tuple[str, List[str]]:
    """
    Divide il blocco YAML monolitico del modello in:
    - meta_text: tutto prima del primo # ── DOC N ──
    - doc_texts: lista di chunk per ogni documento

    Il modello produce un unico blocco con:
      audit: ...
      azienda: ...
      # SEZIONE 05
      # ── DOC 1 ──
      tipo: OFF
      ...
      # ── DOC 2 ──
      tipo: PRO
      ...
    """
    # Pattern separator primario: linee come "# ── DOC 1 ──", "# --- DOC 1 ---",
    # "# — DOC 1 —" (em-dash), "# – DOC 1 –" (en-dash), "# *** DOC 1 ***", ecc.
    # Accetta ampio set di decorazioni; sinonimi DOC/SCHEDA/DOCUMENTO.
    doc_sep = re.compile(
        r'^[ \t]*#[ \t]*[─\-═–—*_=.·•]*[ \t]*(?:DOC|SCHEDA|DOCUMENTO)[ \t]+\d+',
        re.MULTILINE | re.IGNORECASE
    )

    positions = [(m.start(), m.end()) for m in doc_sep.finditer(yaml_content)]

    if positions:
        meta_text = yaml_content[:positions[0][0]]
        doc_texts = []
        for i, (start, _) in enumerate(positions):
            end = positions[i + 1][0] if i + 1 < len(positions) else len(yaml_content)
            doc_texts.append(yaml_content[start:end])
        return meta_text, doc_texts

    # FALLBACK: il modello non ha usato il separatore richiesto.
    # Splittiamo sulle righe `^tipo:` di top-level (indentazione 0), che
    # segnano sempre l'inizio di una nuova scheda documento secondo lo schema.
    tipo_line = re.compile(r'^tipo[ \t]*:[ \t]*["\']?\S', re.MULTILINE)
    tipo_positions = [m.start() for m in tipo_line.finditer(yaml_content)]

    # Se c'e' solo un `tipo:` e si trova nella prima meta' → probabilmente
    # e' dentro il blocco META (campi aziendali o indice), non una scheda.
    # Serve almeno 1 `tipo:` oltre al primo quarto del testo per considerarlo
    # una scheda dedicata. Se 2+ `tipo:` → splitta comunque.
    if len(tipo_positions) >= 2:
        meta_text = yaml_content[:tipo_positions[0]]
        doc_texts = []
        for i, start in enumerate(tipo_positions):
            end = tipo_positions[i + 1] if i + 1 < len(tipo_positions) else len(yaml_content)
            doc_texts.append(yaml_content[start:end])
        return meta_text, doc_texts

    if len(tipo_positions) == 1 and tipo_positions[0] > len(yaml_content) // 4:
        # Un solo doc nel batch, inizia dopo il META
        return yaml_content[:tipo_positions[0]], [yaml_content[tipo_positions[0]:]]

    # Nessun separatore e nessun `tipo:` top-level → tutto META (o formato diverso)
    return yaml_content, []


def parse_structured_response(raw_text: str) -> Optional[Dict]:
    """
    Converte il testo grezzo YAML prodotto da analyze_batch_structured()
    in un dict Python strutturato.

    Il modello produce UN SINGOLO blocco ```yaml``` per batch con:
    - Blocco META in cima (audit, azienda, abbrev_aggiunte, indice)
    - Documenti separati da commenti  # ── DOC N ──
    - Tabelle Markdown embedded come dati
    - Batch multipli separati da  ---

    Returns:
        dict strutturato, oppure None se testo vuoto o non parsabile (mai eccezione).
    """
    if not raw_text or not raw_text.strip():
        return None

    if not HAS_YAML:
        print("[PARSER] PyYAML non installato — eseguire: pip install pyyaml")
        return None

    try:
        # Aggrega tutti i batch (separati da --- nel testo completo)
        # Estrai contenuto da tutti i blocchi ```yaml...```
        yaml_blocks = _extract_yaml_blocks(raw_text)
        if not yaml_blocks:
            # Nessun fence → prova a trattare il testo intero come YAML raw
            yaml_blocks = [(0, raw_text)]

        meta: Dict = {"audit": {}, "azienda": {}, "indice": [], "abbrev_aggiunte": []}
        sezioni_dict: Dict[str, Dict] = {}
        # Candidate per il nome azienda, con score di priorita' della fonte
        # (più alto = più affidabile). Tiene traccia di tutti i batch che
        # hanno emesso un `azienda.nome`, poi sceglie il migliore.
        azienda_candidates: List[Tuple[int, Dict]] = []

        for block_idx, (_pos, block_content) in enumerate(yaml_blocks):
            # Estrai tabelle Markdown PRIMA del parsing YAML
            clean_content, md_tables = _extract_markdown_tables(block_content)

            # Dividi in META + doc chunks
            meta_text, doc_texts = _split_into_meta_and_docs(clean_content)
            docs_in_block = 0  # per logging diagnostico

            # --- Parsa META ---
            meta_clean = re.sub(r'^[ \t]*#.*$', '', meta_text, flags=re.MULTILINE)
            meta_clean = re.sub(r'(\S)\s+#[^"\']*$', r'\1', meta_clean, flags=re.MULTILINE)
            parsed_meta = _safe_yaml_load(meta_clean)
            block_meta: Dict = {}
            if isinstance(parsed_meta, dict):
                block_meta = _parse_meta_block(meta_clean)
                if block_meta.get("audit") and not meta.get("audit", {}).get("norma_principale"):
                    meta["audit"] = block_meta["audit"]
                meta["indice"] = meta.get("indice", []) + block_meta.get("indice", [])
                meta["abbrev_aggiunte"] = meta.get("abbrev_aggiunte", []) + block_meta.get("abbrev_aggiunte", [])

            # --- Parsa documenti ---
            block_tipi: List[str] = []  # tipi documento presenti in questo batch
            for doc_chunk in doc_texts:
                doc = _yaml_chunk_to_doc(doc_chunk, md_tables)
                if not doc:
                    continue
                docs_in_block += 1
                block_tipi.append(str(doc.get("tipo", "")).lower())

                # Determina sezione dalla categoria del documento
                cat = str(doc.get("categoria", "") or "")
                cat_match = re.match(r'(\d+)', cat)
                sid = cat_match.group(1).zfill(2) if cat_match else "18"
                sname = cat if cat else "ALTRI"

                if sid not in sezioni_dict:
                    sezioni_dict[sid] = {"id": sid, "nome": sname, "documenti": []}
                sezioni_dict[sid]["documenti"].append(doc)

            # Log diagnostico per-batch (aiuta a trovare batch che perdono DOC)
            # ASCII-only per compatibilita' Windows cp1252 stdout.
            print(f"[PARSER] Batch #{block_idx}: {len(block_content)} chars -> "
                  f"{len(doc_texts)} chunks -> {docs_in_block} schede valide")

            # Score azienda_nome: priorita' al batch che contiene fonti affidabili
            az_nome = (block_meta.get("azienda", {}) or {}).get("nome", "") if block_meta else ""
            if az_nome and str(az_nome).strip():
                # Score alto = fonte attendibile (visura, statuto, attestazione SOA, fattura)
                # Score basso = fonte dubbia (solo DVR/CV/formazione nel batch)
                tipi_joined = " ".join(block_tipi)
                score = 0
                if re.search(r'visura|camerale|cciaa|registro imprese', tipi_joined):
                    score += 100
                if re.search(r'statuto|atto costitutivo|atto notarile', tipi_joined):
                    score += 80
                if re.search(r'attestazione soa|certificato iso|rating legalit', tipi_joined):
                    score += 60
                if re.search(r'fattura|bilancio', tipi_joined):
                    score += 30
                if re.search(r'\bdvr\b|curriculum|cv |attestato.{0,30}formazione|registro.{0,5}presenze', tipi_joined):
                    score -= 50  # penalita': il nome e' probabilmente consulente/formatore
                azienda_candidates.append((score, block_meta.get("azienda", {}) or {}))
                print(f"[PARSER] Batch #{block_idx}: candidato azienda='{az_nome}' score={score} "
                      f"(tipi={block_tipi[:3]})")

        # Scegli la migliore candidata azienda: score più alto vince
        if azienda_candidates:
            azienda_candidates.sort(key=lambda t: t[0], reverse=True)
            best_score, best_azienda = azienda_candidates[0]
            meta["azienda"] = best_azienda
            print(f"[PARSER] Nome azienda scelto: '{best_azienda.get('nome', '')}' (score={best_score})")

        sezioni = [sezioni_dict[k] for k in sorted(sezioni_dict.keys())]

        if not meta.get("azienda") and not sezioni:
            print("[PARSER] Output non riconoscibile — tentativo fallback JSON")
            return _parse_json_narrativo_fallback(raw_text)

        n_docs = sum(len(s["documenti"]) for s in sezioni)
        print(f"[PARSER] OK: {len(sezioni)} sezioni, {n_docs} documenti")

        result = {"meta": meta, "sezioni": sezioni}
        # FIX #4 + #6: scrub privacy & campi legacy (commessa, cf, data_nascita…)
        _scrub_tree(result)
        # FASE C: soft quality warnings (non bloccante) su documenti critici
        _soft_audit_warnings(result)
        return result

    except Exception as e:
        print(f"[PARSER] Errore inatteso: {e}")
        return _parse_json_narrativo_fallback(raw_text)


def _parse_json_narrativo_fallback(raw_text: str) -> Optional[Dict]:
    """
    Fallback: converte l'output JSON della pipeline narrativa (lista di dict con
    'numero', 'categoria', 'sottotitolo', 'contenuto') nel formato strutturato
    atteso da generate_structured_evidence_docx.

    Questo path viene attivato solo quando il modello ignora le istruzioni YAML
    (es. system_prompt contamina il contesto). Il fix primario è skip_system_prompt=True
    in analyze_batch_structured; questo fallback è la rete di sicurezza.
    """
    if not raw_text or not raw_text.strip():
        return None
    try:
        # Estrai blocco JSON (può essere dentro ```json...``` o raw)
        json_match = re.search(r'```(?:json|JSON)?\s*\n?(.*?)```', raw_text, re.DOTALL)
        json_str = json_match.group(1) if json_match else raw_text.strip()

        data = json.loads(json_str)
        if not isinstance(data, list) or not data:
            return None

        # Controlla che sia il formato narrativo (campo 'contenuto' o 'sottotitolo')
        first = data[0]
        if not isinstance(first, dict):
            return None
        if "contenuto" not in first and "sottotitolo" not in first:
            return None

        print(f"[PARSER] Fallback JSON narrativo: {len(data)} documenti trovati")

        # Raggruppa per categoria → sezione
        sezioni_dict: Dict[str, Dict] = {}
        for item in data:
            cat_raw = str(item.get("categoria", "ALTRI")).strip()
            # Cerca id numerico nel nome categoria (es. "05 · OPERATIVITÀ")
            id_match = re.match(r'(\d+)', cat_raw)
            sid = id_match.group(1).zfill(2) if id_match else "18"
            sname = cat_raw if cat_raw else "ALTRI"

            if sid not in sezioni_dict:
                sezioni_dict[sid] = {"id": sid, "nome": sname, "documenti": []}

            titolo = str(item.get("sottotitolo", item.get("titolo", "Documento"))).strip()
            contenuto = str(item.get("contenuto", "")).strip()
            ente = str(item.get("ente_auditato", "")).strip()

            doc = {
                "tipo": "DOC",
                "categoria": sname,
                "categorie_secondarie": [],
                "titolo": titolo,
                "riferimento": "",
                "data_doc": "",
                "data_scadenza": "",
                "emesso_da": ente,
                "soggetto": ente,
                "norme_pertinenti": [],
                "firme": {},
                "note_audit": "",
                "cluster": {"Contenuto documento": {"testo": contenuto}}
            }
            sezioni_dict[sid]["documenti"].append(doc)

        sezioni = [sezioni_dict[k] for k in sorted(sezioni_dict.keys())]
        return {
            "meta": {"audit": {}, "azienda": {}, "indice": [], "abbrev_aggiunte": []},
            "sezioni": sezioni
        }

    except Exception as e:
        print(f"[PARSER] Fallback JSON narrativo fallito: {e}")
        return None


def extract_company_name_from_meta(parsed: Dict) -> str:
    """
    Estrae il nome azienda dal blocco META del dict strutturato.

    Args:
        parsed: dict restituito da parse_structured_response()

    Returns:
        Nome azienda in maiuscolo, oppure "AZIENDA NON IDENTIFICATA" se assente/vuoto.
    """
    if not parsed or not isinstance(parsed, dict):
        return "AZIENDA NON IDENTIFICATA"

    meta = parsed.get("meta", {})
    if not isinstance(meta, dict):
        return "AZIENDA NON IDENTIFICATA"

    azienda = meta.get("azienda", {})
    if not isinstance(azienda, dict):
        return "AZIENDA NON IDENTIFICATA"

    nome = str(azienda.get("nome", "") or "").strip()

    if nome and nome.lower() not in ("n.d.", "n/a", "", "none", "null"):
        return nome.upper()

    return "AZIENDA NON IDENTIFICATA"


# ==============================================================================
# TEST STANDALONE
# ==============================================================================

if __name__ == "__main__":
    print("=== Test structured_evidence_parser ===")
    print(f"PyYAML: {'OK' if HAS_YAML else 'NON INSTALLATO — eseguire: pip install pyyaml'}")

    # Test extract_company_name_from_meta
    assert extract_company_name_from_meta({}) == "AZIENDA NON IDENTIFICATA"
    assert extract_company_name_from_meta({"meta": {"azienda": {"nome": "TEST SRL"}}}) == "TEST SRL"
    assert extract_company_name_from_meta({"meta": {"azienda": {"nome": "n.d."}}}) == "AZIENDA NON IDENTIFICATA"
    print("✅ extract_company_name_from_meta: OK")

    # Test parse_structured_response con input vuoto
    assert parse_structured_response("") is None
    assert parse_structured_response("   ") is None
    assert parse_structured_response("testo completamente invalido senza yaml") is None
    print("✅ parse_structured_response (input invalidi): OK")

    if HAS_YAML:
        # Formato reale prodotto dal PROMPT UNIVERSALE: un singolo blocco yaml
        # con meta in testa e documenti separati da `# ── DOC N ──`.
        fixture = """
```yaml
azienda:
  nome: "TEST S.R.L."
  piva: "12345678901"
  sede: "Via Roma 1 — 20100 Milano (MI)"

abbrev_aggiunte: []
indice:
  - {n: 1, tipo: "VIS", titolo: "Visura Camerale", categoria: "08 · LEGALE/SOCIETARIA"}

# ── DOC 1 ──────────────────────────────────────────────────
tipo: "Visura Camerale"
categoria: "08 · LEGALE/SOCIETARIA"
titolo: "Visura Camerale TEST S.R.L."
riferimento: "n.d."
data_doc: 15/01/2026
data_scadenza: "non applicabile"
emesso_da: "CCIAA Milano"
soggetto: "TEST S.R.L."
norme_pertinenti: ["ISO 9001:2015"]

ragione_sociale: "TEST S.R.L."
piva: "12345678901"
forma_giuridica: "S.r.l."

firme:
  emittente: Presente
  ricevente: "n.d."
  data_firma: "n.d."

note_audit: ""
```
"""
        result = parse_structured_response(fixture)
        assert result is not None, "parse_structured_response fixture → doveva ritornare dict"
        assert "meta" in result
        assert "sezioni" in result
        assert extract_company_name_from_meta(result) == "TEST S.R.L."
        assert len(result["sezioni"]) == 1, f"Sezioni attese=1, trovate={len(result['sezioni'])}"
        assert result["sezioni"][0]["id"] == "08"
        # FIX #4: commessa eliminata dal doc
        doc0 = result["sezioni"][0]["documenti"][0]
        assert "commessa" not in doc0, "commessa deve essere rimossa dal doc"
        print("✅ parse_structured_response (fixture YAML): OK")
        print(f"   Sezioni trovate: {len(result['sezioni'])}")
        print(f"   Documenti: {sum(len(s['documenti']) for s in result['sezioni'])}")
        print(f"   Azienda: {extract_company_name_from_meta(result)}")

        # Test privacy stripping: CF persona fisica deve sparire
        priv_fixture = """
```yaml
azienda:
  nome: "ACME"
  piva: "12345678901"

# ── DOC 1 ──
tipo: "Busta Paga"
categoria: "09 · RISORSE UMANE E LAVORO"
titolo: "Busta paga gennaio"
lavoratore: "Mario Rossi"
cf_lavoratore: "RSSMRA80A01H501Z"
nota: "Nato il 01/01/1980 a Roma"
```
"""
        priv_res = parse_structured_response(priv_fixture)
        assert priv_res is not None
        dumped = json.dumps(priv_res, ensure_ascii=False)
        assert "RSSMRA80A01H501Z" not in dumped, "CF persona fisica NON strippato"
        assert "nato il 01/01/1980" not in dumped.lower(), "Data nascita NON strippata"
        assert "01/01/1980" not in dumped, "Data nascita raw NON strippata"
        print("✅ Privacy stripper (CF + data nascita): OK")

        # FASE C: soft warning su Visura superficiale
        shallow_fixture = """
```yaml
azienda:
  nome: "ACME"
  piva: "12345678901"

# ── DOC 1 ──
tipo: "Visura Camerale"
categoria: "08 · LEGALE/SOCIETARIA"
titolo: "Visura Camerale ACME"

certificazioni:
  soa: "presente"
  albi: "si"
  rating_legalita: "ok"
```
"""
        warnings_captured: List[str] = []
        import builtins as _b
        real_print = _b.print
        def _capture(*args, **kw):
            msg = " ".join(str(a) for a in args)
            if "[QUALITY WARN]" in msg:
                warnings_captured.append(msg)
            real_print(*args, **kw)
        _b.print = _capture
        try:
            parse_structured_response(shallow_fixture)
        finally:
            _b.print = real_print
        assert any("soa" in w.lower() for w in warnings_captured), \
            f"Atteso warn su 'soa' superficiale, trovati: {warnings_captured}"
        print(f"✅ Soft quality warnings: {len(warnings_captured)} emessi su Visura superficiale")
    else:
        print("⚠️  Test fixture saltato — PyYAML non installato")

    print("\n✅ Tutti i test passati.")
