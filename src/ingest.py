import pandas as pd

df = pd.read_csv('data/raw/uniprotkb_Human_proteins_AND_model_orga_2026_03_20.tsv', sep='\t')

docs = []

cols = [
    'Entry',
    'Protein names',
    'Gene Names',
    'Function [CC]',
    'Subcellular location [CC]',
    'Gene Ontology (biological process)',
    'Involvement in disease'
]

for _, row in df.iterrows():
    text = f"""
        Protein: {row['Protein names']}
        Gene: {row['Gene Names']}
        Function: {row['Function [CC]']}
        Location: {row['Subcellular location [CC]']}
        Biological Process: {row['Gene Ontology (biological process)']}
        Disease: {row['Involvement in disease']}
        """
    
    docs.append({
        "text": text.strip(),
        "metadata": {
            "entry": row['Entry'],
            "length": row.get('Length', None)
        }
    })