import json
from collections import Counter

d = json.load(open('data/daily_report.json', 'r', encoding='utf-8'))
prc = [o for o in d['orbits'] if o.get('is_prc') == True]
print(f"Total PRC satellites: {len(prc)}")

# Altitude distribution
alt_buckets = Counter()
status_counts = Counter()
for o in prc:
    alt = o.get('alt', 0)
    status = o.get('status', 'unknown')
    status_counts[status] += 1
    if alt < 10:
        alt_buckets['<10km (decayed)'] += 1
    elif alt < 400:
        alt_buckets['10-400km'] += 1
    elif alt < 600:
        alt_buckets['400-600km'] += 1
    elif alt < 1000:
        alt_buckets['600-1000km'] += 1
    elif alt < 2000:
        alt_buckets['1000-2000km'] += 1
    elif alt < 36000:
        alt_buckets['2000-36000km (MEO)'] += 1
    else:
        alt_buckets['>36000km (GEO)'] += 1

print("\nStatus breakdown:")
for s, c in status_counts.most_common():
    print(f"  {s}: {c}")

print("\nAltitude breakdown:")
for b, c in sorted(alt_buckets.items()):
    print(f"  {b}: {c}")

# Show active PRC with insurance
prc_insured = [o for o in d['orbits'] if o.get('orbit_risk') is not None]
active_insured = [o for o in prc_insured if o.get('alt', 0) > 10]
print(f"\nPRC insured total: {len(prc_insured)}, active (alt>10km): {len(active_insured)}")
if active_insured:
    for o in active_insured[:10]:
        print(f"  {o['name']:30s} alt={o['alt']:>9.1f}km  risk={o['orbit_risk']:.4e}  pc={o['pc_after']:.4e}  claim={o['claim_int']:.6f}  prem={o['premium_rate']:.4f}%  reserve=${o['reserve']:.0f}")
