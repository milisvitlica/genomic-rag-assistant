import pandas as pd

df = pd.read_csv('data/uniprotkb_Human_proteins_AND_model_orga_2026_03_20.tsv', sep='\t')

df.head(100).to_markdown()

# documents = []
# for _, row in df.iterrows():
#     protein = row.get('Protein', '')
#     gene = row.get('Gene', '')
#     function = row.get('Function', '')
#     location = row.get('Location', '')
#     disease = row.get('Disease', '')

#     doc = f"""Protein: {protein}
# Gene: {gene}
# Function: {function}
# Location: {location}
# Disease: {disease}
# """
#     documents.append(doc.strip())