"""Script per estrarre testo dai file .docx e salvare come .md"""
from docx import Document
import os

checklist_dir = r'c:\Users\user\AUDITORSEMI\webapp\prompts\checklist'
docx_files = ['ISO 27001.docx', 'ISO 37001.docx', 'ISO 39001.docx', 'ISO 50001.docx']

for docx_file in docx_files:
    input_path = os.path.join(checklist_dir, docx_file)
    output_name = docx_file.replace('.docx', '.md').replace(' ', '_')
    output_path = os.path.join(checklist_dir, output_name)
    
    try:
        doc = Document(input_path)
        text = '\n\n'.join([p.text for p in doc.paragraphs if p.text.strip()])
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(text)
        
        print(f"[OK] Convertito: {docx_file} -> {output_name}")
    except Exception as e:
        print(f"[ERR] Errore con {docx_file}: {e}")

print("Conversione completata!")
