import os, json
import sys
sys.stdout.reconfigure(encoding='utf-8')

OUTPUT_DIR = 'policy_output'
wave1 = ['POL-01','POL-12','POL-08','POL-34','POL-17','POL-09','POL-06','POL-07','POL-14','POL-19','POL-16','POL-33']
wave2 = ['STD-15','STD-26','STD-02','STD-03','STD-11','STD-09','STD-13','STD-04','STD-08','STD-22','STD-14','STD-16','STD-29','STD-05','STD-07','STD-06','STD-12','STD-23','STD-31','STD-32']
wave3 = ['PRC-01','PRC-02','PRC-03','PRC-04','PRC-05','PRC-30','PRC-25','PRC-26','PRC-27','PRC-22','PRC-09','PRC-33','PRC-31','PRC-43','PRC-44','PRC-32','PRC-10','PRC-40','PRC-15','PRC-21','PRC-23','PRC-24']

ok, missing = 0, []

print("Wave 1 — Foundation Policies:")
for doc_id in wave1:
    docx = os.path.join(OUTPUT_DIR, f'{doc_id}.docx')
    jp   = os.path.join(OUTPUT_DIR, f'{doc_id}.json')
    if os.path.exists(docx) and os.path.exists(jp):
        with open(jp, encoding='utf-8') as f: data = json.load(f)
        clauses = len(data.get('policy_clauses', []))
        size = os.path.getsize(docx)
        title = data.get('meta',{}).get('title_ar','')[:40]
        print(f"  OK  {doc_id}  {clauses} clauses  {size//1024}KB  {title}")
        ok += 1
    else:
        print(f"  MISSING  {doc_id}")
        missing.append(doc_id)

print()
print("Wave 2 — Core Standards:")
for doc_id in wave2:
    docx = os.path.join(OUTPUT_DIR, f'{doc_id}.docx')
    jp   = os.path.join(OUTPUT_DIR, f'{doc_id}.json')
    if os.path.exists(docx) and os.path.exists(jp):
        with open(jp, encoding='utf-8') as f: data = json.load(f)
        clusters = data.get('domain_clusters', [])
        nc = len(clusters)
        nq = sum(len(c.get('clauses',[])) for c in clusters)
        size = os.path.getsize(docx)
        print(f"  OK  {doc_id}  {nc} clusters / {nq} clauses  {size//1024}KB")
        ok += 1
    else:
        print(f"  MISSING  {doc_id}")
        missing.append(doc_id)

print()
print("Wave 3 — High-Impact Procedures:")
for doc_id in wave3:
    docx = os.path.join(OUTPUT_DIR, f'{doc_id}.docx')
    jp   = os.path.join(OUTPUT_DIR, f'{doc_id}.json')
    if os.path.exists(docx) and os.path.exists(jp):
        with open(jp, encoding='utf-8') as f: data = json.load(f)
        phases = data.get('phases', [])
        np_ = len(phases)
        ns  = sum(len(p.get('steps',[])) for p in phases)
        size = os.path.getsize(docx)
        print(f"  OK  {doc_id}  {np_} phases / {ns} steps  {size//1024}KB")
        ok += 1
    else:
        print(f"  MISSING  {doc_id}")
        missing.append(doc_id)

print()
print(f"TOTAL: {ok}/54 generated  |  {len(missing)} missing: {missing}")
