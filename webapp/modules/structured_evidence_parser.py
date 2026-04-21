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
    'riferimento', 'commessa', 'data_doc', 'data_scadenza',
    'emesso_da', 'soggetto', 'norme_pertinenti', 'firme', 'note_audit'
})


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
    """
    # Accetta yaml, YAML, json, JSON, o nessun tag — il parser tenta comunque
    pattern = re.compile(r'```(?:yaml|YAML|json|JSON)?\s*\n(.*?)```', re.DOTALL)
    return [(m.start(), m.group(1)) for m in pattern.finditer(text)]


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


def _yaml_chunk_to_doc(chunk: str, tables: Dict) -> Optional[Dict]:
    """
    Parsa un singolo chunk YAML (un documento) in dict.
    Ricostruisce le tabelle Markdown come cluster.
    Gestisce campi con commenti inline (tipo: CNC # commento).
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

    parsed = _safe_yaml_load(clean_chunk)
    if not isinstance(parsed, dict):
        return None

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
    # Garantisce presenza campi minimi
    for field in ('tipo', 'categoria', 'categorie_secondarie', 'titolo',
                  'riferimento', 'commessa', 'data_doc', 'data_scadenza',
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
    # Pattern separator: linee come "# ── DOC 1 ──────" o "# --- DOC 1 ---"
    doc_sep = re.compile(
        r'^[ \t]*#[ \t]*[─\-─═\-]+[ \t]*DOC[ \t]+\d+',
        re.MULTILINE | re.IGNORECASE
    )

    positions = [(m.start(), m.end()) for m in doc_sep.finditer(yaml_content)]

    if not positions:
        # Nessun separatore — tutto è META (o formato diverso)
        return yaml_content, []

    meta_text = yaml_content[:positions[0][0]]
    doc_texts = []
    for i, (start, _) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(yaml_content)
        doc_texts.append(yaml_content[start:end])

    return meta_text, doc_texts


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

        for _pos, block_content in yaml_blocks:
            # Estrai tabelle Markdown PRIMA del parsing YAML
            clean_content, md_tables = _extract_markdown_tables(block_content)

            # Dividi in META + doc chunks
            meta_text, doc_texts = _split_into_meta_and_docs(clean_content)

            # --- Parsa META ---
            # Rimuovi commenti standalone prima del parsing
            meta_clean = re.sub(r'^[ \t]*#.*$', '', meta_text, flags=re.MULTILINE)
            meta_clean = re.sub(r'(\S)\s+#[^"\']*$', r'\1', meta_clean, flags=re.MULTILINE)
            parsed_meta = _safe_yaml_load(meta_clean)
            if isinstance(parsed_meta, dict):
                block_meta = _parse_meta_block(meta_clean)
                # Merge: i dati del primo batch che ha azienda vincono
                if block_meta.get("azienda", {}).get("nome") and not meta.get("azienda", {}).get("nome"):
                    meta["azienda"] = block_meta["azienda"]
                if block_meta.get("audit") and not meta.get("audit", {}).get("norma_principale"):
                    meta["audit"] = block_meta["audit"]
                meta["indice"] = meta.get("indice", []) + block_meta.get("indice", [])
                meta["abbrev_aggiunte"] = meta.get("abbrev_aggiunte", []) + block_meta.get("abbrev_aggiunte", [])

            # --- Parsa documenti ---
            for doc_chunk in doc_texts:
                doc = _yaml_chunk_to_doc(doc_chunk, md_tables)
                if not doc:
                    continue

                # Determina sezione dalla categoria del documento
                cat = str(doc.get("categoria", "") or "")
                cat_match = re.match(r'(\d+)', cat)
                sid = cat_match.group(1).zfill(2) if cat_match else "18"
                sname = cat if cat else "ALTRI"

                if sid not in sezioni_dict:
                    sezioni_dict[sid] = {"id": sid, "nome": sname, "documenti": []}
                sezioni_dict[sid]["documenti"].append(doc)

        sezioni = [sezioni_dict[k] for k in sorted(sezioni_dict.keys())]

        if not meta.get("azienda") and not sezioni:
            print("[PARSER] Output non riconoscibile — tentativo fallback JSON")
            return _parse_json_narrativo_fallback(raw_text)

        n_docs = sum(len(s["documenti"]) for s in sezioni)
        print(f"[PARSER] OK: {len(sezioni)} sezioni, {n_docs} documenti")
        return {"meta": meta, "sezioni": sezioni}

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
                "commessa": "",
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
        fixture = """
```yaml
audit:
  data_estrazione: 18/04/2026
  norma_principale: "ISO 9001:2015"
  tipo_audit: "Sorveglianza A1"
  docs_estratti: 1
  docs_analizzati: 1

azienda:
  nome: "TEST S.R.L."
  cf: "12345678901"
  sede: "Via Roma 1 — 20100 Milano (MI)"

abbrev_aggiunte: []
indice:
  - {n: 1, tipo: "VIS", titolo: "Visura Camerale", categoria: "08 · LEGALE/SOCIETARIA", norme: ["ISO 9001:2015"]}
```

## SEZIONE 08 · LEGALE/SOCIETARIA

```yaml
tipo: VIS
categoria: "08 · LEGALE/SOCIETARIA"
titolo: "Visura Camerale TEST S.R.L."
riferimento: "n.d."
commessa: "n.d."
data_doc: 15/01/2026
data_scadenza: "non applicabile"
emesso_da: "CCIAA Milano"
soggetto: "TEST S.R.L."
norme_pertinenti: ["ISO 9001:2015"]

ragione_sociale: "TEST S.R.L."
codice_fiscale: "12345678901"
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
        assert len(result["sezioni"]) == 1
        assert result["sezioni"][0]["id"] == "08"
        print("✅ parse_structured_response (fixture YAML): OK")
        print(f"   Sezioni trovate: {len(result['sezioni'])}")
        print(f"   Documenti: {sum(len(s['documenti']) for s in result['sezioni'])}")
        print(f"   Azienda: {extract_company_name_from_meta(result)}")
    else:
        print("⚠️  Test fixture saltato — PyYAML non installato")

    print("\n✅ Tutti i test passati.")
