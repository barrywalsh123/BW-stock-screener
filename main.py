import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import uvicorn
import yfinance as yf
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Asymmetric Stock Screener")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

executor = ThreadPoolExecutor(max_workers=18)

# ─────────────────────────────────────────────────────────────────────────────
# TREND UNIVERSE
# ─────────────────────────────────────────────────────────────────────────────
TRENDS = {
    "AI Infrastructure": {
        "icon": "⚡", "color": "#6366f1",
        "description": "Data centers, liquid cooling, power delivery, and networking enabling AI compute at scale.",
        "bottleneck": "Power delivery and cooling capacity is the #1 physical constraint limiting GPU cluster density. Every MW of AI compute requires purpose-built infrastructure that takes 2–4 years to build.",
        "why_asymmetric": "For every $1 spent on GPUs, $3–5 must be spent on surrounding infrastructure. Yet infrastructure providers trade at 3–5× lower multiples than the hyperscalers they serve.",
        "catalysts": ["$1T+ AI data center buildout by 2030", "Liquid cooling adoption (>$8B market by 2028)", "AI power demand 10× by 2028", "Utility grid constraints driving onsite generation"],
        "tickers": ["SMCI", "VRT", "CRDO", "NPWR", "AEHR", "NVTS", "LIQT"],
    },
    "Defense AI & Autonomy": {
        "icon": "🛡️", "color": "#ef4444",
        "description": "AI-enabled defense platforms, autonomous drones, battlefield intelligence, and next-gen C2 systems.",
        "bottleneck": "DoD has a $900B+ annual budget but legacy primes deliver AI systems on 7–10 year timelines. AI-native vendors ship in months.",
        "why_asymmetric": "Defense AI spending projected to 10× by 2030. Pure-play AI defense companies win disproportionate contract value vs. their market caps.",
        "catalysts": ["REPLICATOR drone program ($500M+)", "FY2025 NDAA AI mandates", "DIU rapid-prototype awards", "NATO autonomous systems adoption"],
        "tickers": ["PLTR", "KTOS", "AVAV", "BBAI", "RCAT", "ACHR"],
    },
    "Quantum Computing": {
        "icon": "⚛️", "color": "#8b5cf6",
        "description": "Quantum hardware and software delivering post-classical computation.",
        "bottleneck": "Error correction breakthrough = overnight multi-trillion dollar opportunity across pharma, logistics, cryptography, and finance.",
        "why_asymmetric": "All major tech companies and governments are investing billions. Small-cap plays already hold government/cloud contracts with massive option value on any breakthrough.",
        "catalysts": ["Google Willow 105-qubit chip (2024)", "Microsoft topological qubit", "DOE $800M quantum funding", "NSA post-quantum mandate"],
        "tickers": ["IONQ", "RGTI", "QBTS", "QUBT"],
    },
    "Nuclear & New Energy": {
        "icon": "☢️", "color": "#f59e0b",
        "description": "Small modular reactors and alternative baseload power for AI data center energy demands.",
        "bottleneck": "The US grid cannot support projected AI power demand by 2027. Every hyperscaler has signed nuclear PPAs. Physical energy is the hard constraint on AI growth.",
        "why_asymmetric": "Nuclear went from 'dead' to 'critical infrastructure' in 18 months. Pre-revenue SMR companies hold LOIs with hyperscalers worth billions.",
        "catalysts": ["Microsoft Three Mile Island PPA (20yr)", "Amazon nuclear PPAs", "NRC SMR approval pipeline", "DOE $900M SMR funding"],
        "tickers": ["NNE", "SMR", "OKLO", "BWXT", "CEG", "GEV"],
    },
    "Edge AI & Specialized Silicon": {
        "icon": "💻", "color": "#10b981",
        "description": "AI inference silicon optimized for edge deployment; specialized accelerators for automotive, medical, and industrial AI.",
        "bottleneck": "Inference is 90%+ of AI compute cost. NVIDIA optimized for training. Massive gap for purpose-built edge AI silicon.",
        "why_asymmetric": "Edge AI market $50B+ by 2030. NVIDIA cannot serve every edge use case cost-effectively. Specialized silicon has defensible IP moats.",
        "catalysts": ["Autonomous vehicle compute requirements", "On-device AI shift", "Medical AI clearances", "Smart manufacturing", "ADAS Level 3+ mandates"],
        "tickers": ["AMBA", "LSCC", "SOUN", "CRDO", "MRVL", "NVTS"],
    },
    "Cybersecurity AI": {
        "icon": "🔒", "color": "#3b82f6",
        "description": "AI-native security platforms defending against AI-generated attacks at machine speed.",
        "bottleneck": "AI-generated attacks made human-speed security responses obsolete. Only AI-native platforms can defend at machine speed.",
        "why_asymmetric": "Security spend is mandatory, not discretionary. AI-native vendors growing 30–50% YoY while legacy vendors stagnate.",
        "catalysts": ["NIS2 EU compliance deadline", "SEC cybersecurity disclosure rules", "AI-generated phishing up 4,000%", "Zero-trust architecture mandates"],
        "tickers": ["CRWD", "S", "VRNS", "CYBR", "TENB", "QLYS"],
    },
    "Space & Satellite Intel": {
        "icon": "🚀", "color": "#06b6d4",
        "description": "LEO satellite connectivity, space-based ISR, and commercial launch services.",
        "bottleneck": "40% of global population lacks reliable broadband. Government ISR demand exploding. SpaceX dominates launch — RKLB is the only credible alternative.",
        "why_asymmetric": "ASTS connects 5.9B people via existing cell phones. RKLB is the only non-SpaceX orbital option for DoD. Both pre-profitability with exponential contract pipelines.",
        "catalysts": ["FCC direct-to-cell approvals", "NATO space ISR contract surge", "Space Force 30% budget growth", "Commercial LEO station program"],
        "tickers": ["ASTS", "RKLB", "SPIR", "GSAT", "MNTS", "PL"],
    },
    "AI Drug Discovery": {
        "icon": "🧬", "color": "#ec4899",
        "description": "AI-accelerated drug discovery, protein structure prediction, multi-omics, and precision medicine.",
        "bottleneck": "Drug discovery takes 12+ years and $2.6B per approved drug. AI compresses to 2–3 years. Pharma cannot build this in-house fast enough.",
        "why_asymmetric": "Every major pharma must partner with AI drug discovery platforms or cede pipeline competitiveness. These companies are strategic M&A targets at 3–5× premiums.",
        "catalysts": ["AlphaFold 3 validation", "FDA AI guidance (2024)", "GLP-1 success driving biotech investment", "AI clinical trial acceleration"],
        "tickers": ["RXRX", "SEER", "ABCL"],
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# PARTNERSHIPS (curated)
# ─────────────────────────────────────────────────────────────────────────────
PARTNERSHIPS = {
    "SMCI":  {"hyperscalers": ["AWS", "Azure", "GCP", "Meta"], "defense": [], "others": ["NVIDIA", "Intel"]},
    "VRT":   {"hyperscalers": ["AWS", "Azure", "GCP", "Meta", "Apple"], "defense": [], "others": []},
    "CRDO":  {"hyperscalers": ["AWS", "Azure", "GCP"], "defense": [], "others": ["Marvell", "Broadcom"]},
    "NPWR":  {"hyperscalers": ["AWS", "Microsoft"], "defense": ["DoD"], "others": []},
    "AEHR":  {"hyperscalers": [], "defense": [], "others": ["ON Semi", "Infineon", "Wolfspeed"]},
    "NVTS":  {"hyperscalers": [], "defense": [], "others": ["EV OEMs", "Industrial Tier 1s"]},
    "LIQT":  {"hyperscalers": [], "defense": [], "others": ["Data center operators"]},
    "PLTR":  {"hyperscalers": ["AWS", "Azure", "GCP"], "defense": ["DoD", "Army", "Air Force", "Navy", "NSA", "NATO"], "others": ["NHS", "CIA"]},
    "KTOS":  {"hyperscalers": [], "defense": ["DoD", "Air Force", "Navy", "DARPA"], "others": []},
    "AVAV":  {"hyperscalers": [], "defense": ["US Army", "Air Force", "NATO", "Israel IDF"], "others": []},
    "BBAI":  {"hyperscalers": ["AWS"], "defense": ["DoD", "DARPA", "DHS", "CBP"], "others": []},
    "RCAT":  {"hyperscalers": [], "defense": ["DoD", "US Army", "SOCOM"], "others": []},
    "ACHR":  {"hyperscalers": [], "defense": ["Air Force", "DoD"], "others": ["United Airlines", "Southwest Airlines"]},
    "IONQ":  {"hyperscalers": ["AWS", "Azure", "GCP"], "defense": ["DoD", "DARPA", "Air Force Research Lab"], "others": ["Hyundai", "Airbus"]},
    "RGTI":  {"hyperscalers": ["Azure"], "defense": ["DARPA", "AFRL"], "others": ["Volkswagen"]},
    "QBTS":  {"hyperscalers": ["AWS"], "defense": [], "others": ["Volkswagen", "Mastercard", "USRA"]},
    "QUBT":  {"hyperscalers": [], "defense": ["NASA", "DoE"], "others": []},
    "NNE":   {"hyperscalers": ["NVIDIA", "AWS"], "defense": [], "others": ["Dominion Energy"]},
    "SMR":   {"hyperscalers": [], "defense": ["DoD", "DOE"], "others": []},
    "OKLO":  {"hyperscalers": ["AWS", "Google"], "defense": ["DOE"], "others": ["Data center operators"]},
    "BWXT":  {"hyperscalers": [], "defense": ["DoD", "US Navy", "NASA"], "others": ["Ontario Power"]},
    "CEG":   {"hyperscalers": ["AWS", "Azure", "GCP", "Meta", "Google"], "defense": [], "others": ["Microsoft"]},
    "GEV":   {"hyperscalers": ["AWS", "Azure", "GCP", "Meta"], "defense": ["DoD"], "others": ["Utilities"]},
    "AMBA":  {"hyperscalers": ["AWS"], "defense": [], "others": ["Rivian", "Togg", "Automotive OEMs"]},
    "LSCC":  {"hyperscalers": [], "defense": ["DoD", "Lockheed", "Raytheon"], "others": ["Tier 1 Auto", "Industrial"]},
    "SOUN":  {"hyperscalers": ["AWS", "Azure"], "defense": [], "others": ["Stellantis", "Honda", "Hyundai", "Kia"]},
    "MRVL":  {"hyperscalers": ["AWS", "Azure", "GCP", "Meta", "Apple"], "defense": [], "others": []},
    "CRWD":  {"hyperscalers": ["AWS", "Azure", "GCP"], "defense": ["DoD", "CISA"], "others": []},
    "S":     {"hyperscalers": ["AWS", "Azure", "GCP"], "defense": ["DoD"], "others": []},
    "VRNS":  {"hyperscalers": ["AWS", "Azure"], "defense": ["DoD", "DISA"], "others": []},
    "CYBR":  {"hyperscalers": ["AWS", "Azure", "GCP"], "defense": ["IDF", "DoD"], "others": []},
    "TENB":  {"hyperscalers": ["AWS", "Azure", "GCP"], "defense": ["US Gov"], "others": []},
    "QLYS":  {"hyperscalers": ["AWS", "Azure", "GCP"], "defense": [], "others": []},
    "ASTS":  {"hyperscalers": [], "defense": [], "others": ["AT&T", "Verizon", "Vodafone", "Rakuten", "Bell Canada"]},
    "RKLB":  {"hyperscalers": [], "defense": ["DoD", "NRO", "DARPA", "NASA", "Space Force"], "others": []},
    "SPIR":  {"hyperscalers": ["AWS"], "defense": ["NRO", "DoD", "DARPA", "Ukraine MoD"], "others": ["NOAA", "ESA"]},
    "GSAT":  {"hyperscalers": [], "defense": [], "others": ["Apple (Emergency SOS)", "T-Mobile", "MediaTek"]},
    "MNTS":  {"hyperscalers": ["AWS"], "defense": ["DARPA", "Air Force", "NRO"], "others": []},
    "PL":    {"hyperscalers": [], "defense": ["NRO", "DoD", "Ukraine"], "others": ["USDA", "ESA", "World Bank"]},
    "RXRX":  {"hyperscalers": ["AWS", "Google"], "defense": [], "others": ["NVIDIA", "Sanofi", "AstraZeneca", "Bayer"]},
    "SEER":  {"hyperscalers": [], "defense": ["NIH"], "others": ["Roche", "Pfizer", "Mayo Clinic"]},
    "ABCL":  {"hyperscalers": ["AWS"], "defense": [], "others": ["AbbVie", "Merck", "Genentech", "Gilead"]},
    # RADAR tickers
    "KULR":  {"hyperscalers": [], "defense": ["NASA", "DoD"], "others": ["Samsung SDI", "SpaceX supply chain"]},
    "BKSY":  {"hyperscalers": [], "defense": ["DoD", "NRO", "In-Q-Tel"], "others": []},
    "ARBE":  {"hyperscalers": [], "defense": ["IDF (pedigree)"], "others": ["Auto OEMs (pipeline)", "SAIC"]},
    "KOPN":  {"hyperscalers": [], "defense": ["DoD", "Army", "SOCOM"], "others": ["Industrial AR"]},
    "CEVA":  {"hyperscalers": ["AWS", "Apple", "Samsung"], "defense": [], "others": ["MediaTek", "Qualcomm licensees", "100s of chip cos"]},
    "BTBT":  {"hyperscalers": [], "defense": [], "others": ["AI compute customers", "HPC operators"]},
    "FLUX":  {"hyperscalers": [], "defense": [], "others": ["Walmart", "Amazon DCs", "Manufacturing"]},
    "LTBR":  {"hyperscalers": [], "defense": [], "others": ["Centrus Energy", "USNC", "Utilities (discussions)"]},
    "SATL":  {"hyperscalers": [], "defense": ["US Gov", "Argentina MoD", "Middle East govs"], "others": ["UN agencies"]},
    "BFLY":  {"hyperscalers": [], "defense": ["DARPA", "Military medical"], "others": ["Hospital systems", "WHO"]},
    "LAZR":  {"hyperscalers": [], "defense": [], "others": ["Volvo", "Mercedes-Benz", "NVIDIA (partnership)"]},
    "EVLV":  {"hyperscalers": [], "defense": ["DHS", "TSA (pilots)"], "others": ["Schools", "Stadiums", "Venues"]},
    "ONDS":  {"hyperscalers": [], "defense": ["DoD", "DHS"], "others": ["BNSF Railway", "CSX", "AAR"]},
    "UUUU":  {"hyperscalers": [], "defense": ["DoE", "DoD"], "others": ["Uranium utilities", "EV magnet supply chain"]},
    "POWL":  {"hyperscalers": ["AWS (EPC channel)"], "defense": [], "others": ["US utilities", "LNG operators", "Hyperscaler EPCs"]},
    "IREN":  {"hyperscalers": [], "defense": [], "others": ["NVIDIA", "Enterprise AI customers"]},
    "NXT":   {"hyperscalers": [], "defense": [], "others": ["Major IPPs", "Utility-scale developers"]},
    "GRRR":  {"hyperscalers": [], "defense": ["Egypt MoI"], "others": ["Asian municipalities"]},
    "LUNR":  {"hyperscalers": [], "defense": ["NASA", "DoD"], "others": []},
    "RDW":   {"hyperscalers": [], "defense": ["NASA", "DoD"], "others": ["ESA", "Commercial space stations"]},
    "INDI":  {"hyperscalers": [], "defense": [], "others": ["Major auto OEMs/Tier 1s"]},
    "HIMX":  {"hyperscalers": ["Meta"], "defense": [], "others": ["Major AR program OEMs"]},
    "AISP":  {"hyperscalers": [], "defense": ["DoD", "DHS", "Federal LEA"], "others": []},
    "BE":    {"hyperscalers": ["Hyperscaler interest"], "defense": [], "others": ["AEP", "SK ecosystem"]},
    "VLD":   {"hyperscalers": [], "defense": ["SpaceX (former)", "Defense primes"], "others": []},
}

INNOVATION_SCORES = {
    "IONQ": 96, "RGTI": 91, "QBTS": 87, "QUBT": 82,
    "RXRX": 93, "ABCL": 89, "SEER": 83,
    "ASTS": 90, "RKLB": 87, "SPIR": 82, "MNTS": 84, "GSAT": 71, "PL": 79,
    "AMBA": 83, "CRDO": 84, "MRVL": 80, "LSCC": 77, "SOUN": 80, "NVTS": 82,
    "PLTR": 90, "BBAI": 84, "KTOS": 80, "AVAV": 77, "RCAT": 80, "ACHR": 87,
    "NNE": 87, "SMR": 84, "OKLO": 92, "BWXT": 74, "CEG": 67, "GEV": 77,
    "SMCI": 72, "VRT": 74, "NPWR": 82, "AEHR": 74, "LIQT": 78,
    "CRWD": 87, "S": 84, "VRNS": 82, "CYBR": 80, "TENB": 74, "QLYS": 72,
    # Radar
    "KULR": 80, "BKSY": 79, "ARBE": 84, "KOPN": 76, "CEVA": 83,
    "BTBT": 68, "FLUX": 72, "LTBR": 86, "SATL": 77, "BFLY": 82,
    "LAZR": 85, "EVLV": 79, "ONDS": 78, "UUUU": 70,
    "POWL": 73, "IREN": 78, "NXT": 80, "GRRR": 76, "LUNR": 84,
    "RDW": 78, "INDI": 81, "HIMX": 76, "AISP": 77, "BE": 79, "VLD": 80,
}

# ─────────────────────────────────────────────────────────────────────────────
# BACKLOG / RPO ($B) — curated from latest filings & earnings calls
# Used to flag companies with high backlog-to-market-cap ratio (forward growth signal)
# ─────────────────────────────────────────────────────────────────────────────
BACKLOG_B = {
    # Defense / AI primes
    "PLTR": 5.7, "KTOS": 1.45, "AVAV": 0.71, "BBAI": 0.42, "RCAT": 0.12, "ACHR": 6.0,
    # Space
    "RKLB": 1.05, "ASTS": 0.80, "SPIR": 0.10, "PL": 0.527, "MNTS": 0.05,
    "LUNR": 0.328, "RDW": 0.37, "BKSY": 0.36,
    # Nuclear / power
    "BWXT": 4.8, "GEV": 119.0, "OKLO": 14.0, "NNE": 0.55, "POWL": 1.4, "BE": 14.5,
    "NXT": 4.5,
    # AI infra
    "SMCI": 4.5, "VRT": 7.4, "CRDO": 0.10, "IREN": 0.0,
    # Quantum
    "IONQ": 0.07, "RGTI": 0.026, "QBTS": 0.024,
    # Cyber (RPO)
    "CRWD": 6.7, "S": 1.05, "VRNS": 0.65, "CYBR": 0.95, "TENB": 0.85, "QLYS": 0.55,
    # Edge silicon
    "AMBA": 0.0, "LSCC": 0.0, "MRVL": 0.0, "INDI": 7.1, "CEVA": 0.0,
    # Drug discovery
    "RXRX": 1.2, "ABCL": 1.5, "SEER": 0.07,
    # Radar
    "ARBE": 0.06, "GRRR": 0.10, "ONDS": 0.041, "AISP": 0.035,
    "KOPN": 0.18, "BFLY": 0.0, "LAZR": 3.4, "EVLV": 0.31, "UUUU": 0.0,
    "LTBR": 0.0, "SATL": 0.06, "KULR": 0.025, "FLUX": 0.07, "BTBT": 0.0, "VLD": 0.30,
}

SECTOR_TAM_SCORES = {
    "Quantum Computing": 98, "AI Drug Discovery": 93, "Defense AI & Autonomy": 91,
    "AI Infrastructure": 92, "Space & Satellite Intel": 89, "Nuclear & New Energy": 89,
    "Edge AI & Specialized Silicon": 88, "Cybersecurity AI": 86,
}

TICKER_TO_TREND: dict = {}
for _t, _d in TRENDS.items():
    for _k in _d["tickers"]:
        TICKER_TO_TREND[_k] = _t

# ─────────────────────────────────────────────────────────────────────────────
# COMPETITORS / COMPS (static, returned as metadata)
# ─────────────────────────────────────────────────────────────────────────────
COMPS = {
    # AI INFRASTRUCTURE
    "SMCI":  {"peers": ["VRT","NPWR","HPE"], "leaders": [{"name":"Dell Technologies","ticker":"DELL","note":"Dominant enterprise server, $100B+ revenue"},{"name":"HP Enterprise","ticker":"HPE","note":"Hybrid cloud infra leader"}], "edge": "NVIDIA-first GPU server designs ship faster than Dell/HPE. Highest revenue concentration in AI servers.", "acquirers": ["DELL","Foxconn","Softbank"]},
    "VRT":   {"peers": ["SMCI","NPWR","ETN"], "leaders": [{"name":"Schneider Electric","ticker":"SBGSF","note":"Global #1 data center power/cooling ($35B rev)"},{"name":"Eaton","ticker":"ETN","note":"Power management, $23B rev, direct competitor"}], "edge": "Only pure-play data center critical infrastructure (power + cooling + IT). No enterprise distraction.", "acquirers": ["Schneider Electric","ABB","Eaton"]},
    "CRDO":  {"peers": ["MRVL","NVTS","AVGO"], "leaders": [{"name":"Broadcom","ticker":"AVGO","note":"Networking silicon giant, $60B+ revenue"},{"name":"Cisco","ticker":"CSCO","note":"Dominant in data center networking"}], "edge": "Credo's Active Electrical Cables are the 'last inch' AI cluster interconnect — complementary to Broadcom, not head-to-head.", "acquirers": ["AVGO","CSCO","Marvell"]},
    "NPWR":  {"peers": ["VRT","SMCI","FLUX"], "leaders": [{"name":"Schneider Electric","ticker":"SBGSF","note":"Grid-scale power solutions"},{"name":"Eaton","ticker":"ETN","note":"Power management systems"}], "edge": "Modular power conversion systems for extreme-density AI compute. Below institutional radar.", "acquirers": ["Schneider Electric","Eaton","ABB"]},
    "AEHR":  {"peers": ["NVTS","COHU"], "leaders": [{"name":"Teradyne","ticker":"TER","note":"Dominant semiconductor test equipment"},{"name":"Cohu","ticker":"COHU","note":"Semiconductor test handler leader"}], "edge": "Monopoly-like position in wafer-level burn-in testing for SiC power chips used in EVs and AI power systems.", "acquirers": ["Teradyne","Cohu","KLA"]},
    "NVTS":  {"peers": ["AEHR","WOLF","STM"], "leaders": [{"name":"Wolfspeed","ticker":"WOLF","note":"SiC wafer manufacturing leader"},{"name":"Onsemi","ticker":"ON","note":"SiC power devices for EVs"}], "edge": "GaN/SiC power semiconductors for EV charging and data center power conversion — 10× more efficient than silicon.", "acquirers": ["Texas Instruments","Onsemi","STMicro"]},
    "LIQT":  {"peers": ["VRT","NPWR"], "leaders": [{"name":"Vertiv","ticker":"VRT","note":"Liquid cooling market leader"},{"name":"Schneider Electric","ticker":"SBGSF","note":"Comprehensive data center cooling"}], "edge": "Silicon carbide membrane technology enables ultra-efficient liquid cooling filtration. Critical niche component.", "acquirers": ["Vertiv","Parker Hannifin"]},
    # DEFENSE AI
    "PLTR":  {"peers": ["BBAI","S","BAH"], "leaders": [{"name":"Lockheed Martin","ticker":"LMT","note":"Largest defense prime, $65B revenue"},{"name":"Booz Allen Hamilton","ticker":"BAH","note":"Government IT/AI services leader"}], "edge": "Only AI platform company that works across ALL branches (CIA, Army, NHS, commercial). Primes must integrate PLTR — they can't build it themselves.", "acquirers": ["Not likely — too large and strategically independent"]},
    "KTOS":  {"peers": ["AVAV","RCAT","ACHR"], "leaders": [{"name":"Northrop Grumman","ticker":"NOC","note":"Autonomous systems (Global Hawk)"},{"name":"Textron","ticker":"TXT","note":"Defense unmanned systems"}], "edge": "Builds affordable, attritable (expendable) drones at a price point defense primes cannot match. USAF specifically needs low-cost autonomous wingmen.", "acquirers": ["Northrop Grumman","L3Harris","Textron"]},
    "AVAV":  {"peers": ["KTOS","RCAT","ACHR"], "leaders": [{"name":"Northrop Grumman","ticker":"NOC","note":"Large HALE drones (Global Hawk)"},{"name":"Boeing","ticker":"BA","note":"Loyal Wingman (MQ-28) program"}], "edge": "Owns the Army small/medium UAS market. Switchblade loitering munition battle-proven in Ukraine. Impossible for primes to undercut at this scale.", "acquirers": ["L3Harris","Northrop Grumman","Textron"]},
    "BBAI":  {"peers": ["PLTR","SPIR","KTOS"], "leaders": [{"name":"Palantir","ticker":"PLTR","note":"Government AI platform at scale"},{"name":"Booz Allen Hamilton","ticker":"BAH","note":"Federal AI/ML services giant"}], "edge": "Specializes in autonomous AI decision-support at the tactical edge. More specialized and lower-cost than PLTR for specific DoD use cases.", "acquirers": ["PLTR","Booz Allen","SAIC","Leidos"]},
    "RCAT":  {"peers": ["KTOS","AVAV","ACHR"], "leaders": [{"name":"Skydio (private)","ticker":"N/A","note":"Leading US autonomous drone"},{"name":"Shield AI (private)","ticker":"N/A","note":"AI-piloted fighter drones, $2B+ valued"}], "edge": "Only NDAA-compliant tactical drones filling the DJI ban vacuum at this price point with thermal + AI. Army Teal drone contract.", "acquirers": ["Textron","L3Harris","AeroVironment"]},
    "ACHR":  {"peers": ["JOBY","LILM","EVEX"], "leaders": [{"name":"Joby Aviation","ticker":"JOBY","note":"eVTOL leader, Toyota backing"},{"name":"Airbus","ticker":"AIR","note":"CityAirbus NextGen eVTOL"}], "edge": "United Airlines LOI + DoD Air Force contract. Faster path to FAA certification than many peers. Commercial + defense dual use.", "acquirers": ["United Airlines","Delta","Stellantis"]},
    # QUANTUM
    "IONQ":  {"peers": ["RGTI","QBTS","QUBT"], "leaders": [{"name":"IBM Quantum","ticker":"IBM","note":"1000+ qubit superconducting, cloud-first"},{"name":"Google Quantum AI","ticker":"GOOGL","note":"Willow chip (2024), massive R&D"},{"name":"Microsoft Azure Quantum","ticker":"MSFT","note":"Topological qubit approach"}], "edge": "Trapped-ion delivers highest gate fidelity (99.9%). Only quantum company simultaneously native on AWS + Azure + Google Cloud.", "acquirers": ["Amazon","Microsoft","IBM","Honeywell"]},
    "RGTI":  {"peers": ["IONQ","QBTS","QUBT"], "leaders": [{"name":"IBM Quantum","ticker":"IBM","note":"Superconducting approach at scale"},{"name":"Google Quantum AI","ticker":"GOOGL","note":"Willow chip breakthrough"}], "edge": "Modular superconducting processor architecture designed for scalability. Azure Quantum partnership de-risks revenue.", "acquirers": ["IBM","Microsoft","Intel"]},
    "QBTS":  {"peers": ["IONQ","RGTI","QUBT"], "leaders": [{"name":"IBM Quantum","ticker":"IBM","note":"Gate-model quantum computing"},{"name":"Google Quantum AI","ticker":"GOOGL","note":"Superconducting quantum hardware"}], "edge": "D-Wave's quantum annealing solves specific optimization problems (logistics, finance, drug discovery) NOW commercially — not waiting for fault tolerance.", "acquirers": ["IBM","Amazon","Mastercard"]},
    "QUBT":  {"peers": ["IONQ","RGTI","QBTS"], "leaders": [{"name":"IBM Quantum","ticker":"IBM","note":"Gate-model leader"},{"name":"Google Quantum AI","ticker":"GOOGL","note":"Superconducting quantum hardware"}], "edge": "Photonic quantum systems and near-term optimization software. NASA contract validates technology at early stage.", "acquirers": ["IBM","Google","Raytheon"]},
    # NUCLEAR
    "NNE":   {"peers": ["SMR","OKLO","BWXT"], "leaders": [{"name":"Westinghouse","ticker":"N/A","note":"Largest global nuclear contractor (private)"},{"name":"GE Hitachi Nuclear","ticker":"GEV","note":"BWRX-300 SMR"}], "edge": "Developing ultra-portable microreactors (ZEUS, ODIN) small enough to power remote data centers and forward operating bases.", "acquirers": ["BWX Technologies","GE Vernova","Westinghouse"]},
    "SMR":   {"peers": ["NNE","OKLO","BWXT"], "leaders": [{"name":"GE Hitachi Nuclear","ticker":"GEV","note":"BWRX-300 SMR market leader"},{"name":"Westinghouse AP300","ticker":"N/A","note":"300 MW SMR (private)"}], "edge": "NuScale's VOYGR is the FIRST and ONLY NRC-approved SMR design in the US. First-mover regulatory advantage.", "acquirers": ["Fluor","Westinghouse"]},
    "OKLO":  {"peers": ["NNE","SMR","BWXT"], "leaders": [{"name":"TerraPower","ticker":"N/A","note":"Fast reactor, Bill Gates-backed (private)"},{"name":"X-energy","ticker":"N/A","note":"Pebble bed HTGR, Amazon PPA (private)"}], "edge": "Aurora compact fast reactor designed for 100% automation. OpenAI CEO Sam Altman is chairman — direct hyperscaler data center positioning.", "acquirers": ["Amazon","Microsoft","Berkshire Hathaway Energy"]},
    "BWXT":  {"peers": ["NNE","SMR","GEV"], "leaders": [{"name":"Northrop Grumman","ticker":"NOC","note":"Nuclear weapons/space"},{"name":"Leidos","ticker":"LDOS","note":"Government nuclear services"}], "edge": "SOLE supplier of nuclear reactors for US Navy submarines and aircraft carriers. Also building space nuclear reactors for NASA/DoD. Irreplaceable.", "acquirers": ["Unlikely — critical defense supplier, government would block"]},
    "CEG":   {"peers": ["VST","NNE","SMR"], "leaders": [{"name":"NextEra Energy","ticker":"NEE","note":"Largest US clean energy company"},{"name":"Duke Energy","ticker":"DUK","note":"Major nuclear fleet operator"}], "edge": "Largest nuclear fleet operator in US (21 reactors). Three Mile Island restart signed 20-year PPA with Microsoft. First-mover for hyperscaler nuclear PPAs.", "acquirers": ["Unlikely — strategic asset, too large"]},
    "GEV":   {"peers": ["ETN","SMCI","VRT"], "leaders": [{"name":"Siemens Energy","ticker":"SMEGY","note":"Gas turbines, grid infrastructure"},{"name":"ABB","ticker":"ABB","note":"Power grid technology"}], "edge": "Only US-based gas turbine manufacturer. AI data center power demand creating multi-year supercycle for gas turbines and grid hardware.", "acquirers": ["Unlikely — critical infrastructure, too large"]},
    # EDGE AI & SILICON
    "AMBA":  {"peers": ["LSCC","NVTS","CEVA"], "leaders": [{"name":"NVIDIA","ticker":"NVDA","note":"Dominant AI chip, Jetson for edge"},{"name":"Qualcomm","ticker":"QCOM","note":"Edge AI in mobile/automotive"},{"name":"Mobileye","ticker":"MBLY","note":"Dominant ADAS chip"}], "edge": "CV/AI chips for security cameras and automotive deliver NVIDIA-competitive vision AI at 10% of the power draw. Purpose-built for edge efficiency.", "acquirers": ["NVIDIA","Qualcomm","Samsung","Renesas"]},
    "LSCC":  {"peers": ["AMBA","CRDO","NVTS"], "leaders": [{"name":"Intel (Altera)","ticker":"INTC","note":"FPGA market (acquired Altera)"},{"name":"AMD (Xilinx)","ticker":"AMD","note":"FPGA market (acquired Xilinx)"}], "edge": "Owns the low-power FPGA market that Intel/AMD don't bother with. Every automotive, industrial, and defense system needs programmable logic.", "acquirers": ["Intel","AMD","Microchip Technology"]},
    "SOUN":  {"peers": ["AMBA","CEVA"], "leaders": [{"name":"Amazon Alexa","ticker":"AMZN","note":"Voice AI cloud service dominant"},{"name":"Google Assistant","ticker":"GOOGL","note":"Cloud voice AI"}], "edge": "Voice AI deployed IN the car with Stellantis, Honda, Hyundai — no cloud latency required. Unlike Alexa/Google, fully offline automotive-grade.", "acquirers": ["Qualcomm","NVIDIA","Amazon","Stellantis"]},
    "MRVL":  {"peers": ["CRDO","AVGO","INTC"], "leaders": [{"name":"Broadcom","ticker":"AVGO","note":"Networking silicon leader"},{"name":"Intel","ticker":"INTC","note":"Data center networking (declining)"}], "edge": "Designs custom AI silicon for AWS (Trainium), Google (TPU), Microsoft. IS the hyperscaler custom chip foundry of choice for data center networking.", "acquirers": ["Samsung","Qualcomm"]},
    # CYBERSECURITY
    "CRWD":  {"peers": ["S","VRNS","CYBR"], "leaders": [{"name":"Palo Alto Networks","ticker":"PANW","note":"Largest cybersecurity pure-play, $100B+"},{"name":"Microsoft Security","ticker":"MSFT","note":"Defender/Sentinel embedded in enterprise"}], "edge": "Falcon platform has 24M+ agent deployments. Only cloud-native XDR from ground up — legacy vendors retrofitted. Network effect = massive switching costs.", "acquirers": ["Unlikely — too large, strategic acquirer themselves"]},
    "S":     {"peers": ["CRWD","VRNS","CYBR"], "leaders": [{"name":"CrowdStrike","ticker":"CRWD","note":"XDR/EDR market leader"},{"name":"Palo Alto Networks","ticker":"PANW","note":"Comprehensive platform"}], "edge": "Fully autonomous AI detection requiring zero human intervention. No human analysts needed for tier-1 alerts = massive cost advantage over legacy SOC teams.", "acquirers": ["Palo Alto Networks","Cisco","Broadcom","IBM"]},
    "VRNS":  {"peers": ["CRWD","S","CYBR"], "leaders": [{"name":"Microsoft Purview","ticker":"MSFT","note":"Data governance built into M365"},{"name":"Symantec/Broadcom DLP","ticker":"AVGO","note":"Legacy DLP leader"}], "edge": "Focuses on data security (who touched what data, when). GDPR/CCPA/SEC compliance spend is mandatory and growing. AI makes threat detection self-improving.", "acquirers": ["Microsoft","Palo Alto Networks","Cisco"]},
    "CYBR":  {"peers": ["CRWD","S","VRNS"], "leaders": [{"name":"BeyondTrust (private)","ticker":"N/A","note":"PAM market leader"},{"name":"Delinea (private)","ticker":"N/A","note":"PAM solutions"}], "edge": "Dominates Privileged Access Management (PAM) — protecting admin credentials. Every enterprise requires PAM for SOC 2/ISO compliance. AI-native identity security.", "acquirers": ["Palo Alto Networks","Cisco","IBM"]},
    "TENB":  {"peers": ["QLYS","CRWD","S"], "leaders": [{"name":"Qualys","ticker":"QLYS","note":"Competing vulnerability management SaaS"},{"name":"Microsoft Defender Vuln Mgmt","ticker":"MSFT","note":"Bundled into M365"}], "edge": "Nessus scanner is the industry standard — 30+ years, 75,000+ organizations. Tenable One converges vuln management, cloud security, and OT/IoT security.", "acquirers": ["Palo Alto Networks","Cisco","CrowdStrike"]},
    "QLYS":  {"peers": ["TENB","CRWD","S"], "leaders": [{"name":"Tenable","ticker":"TENB","note":"Competing vulnerability management"},{"name":"Rapid7","ticker":"RPD","note":"Vulnerability + SIEM"}], "edge": "Cloud-native vulnerability management with 97%+ gross margins. No hardware dependency. Sticky enterprise contracts, profitable at scale.", "acquirers": ["Palo Alto Networks","Broadcom","CrowdStrike"]},
    # SPACE
    "ASTS":  {"peers": ["GSAT","SPIR","PL"], "leaders": [{"name":"SpaceX Starlink","ticker":"N/A","note":"Direct broadband satellite (private, $150B+)"},{"name":"Amazon Kuiper","ticker":"AMZN","note":"LEO broadband constellation"}], "edge": "Connects existing smartphones DIRECTLY — no special hardware needed (unlike Starlink). AT&T, Verizon, Vodafone paying for access. 5.9B potential users.", "acquirers": ["AT&T","Verizon","T-Mobile","Amazon"]},
    "RKLB":  {"peers": ["SPIR","PL","MNTS"], "leaders": [{"name":"SpaceX","ticker":"N/A","note":"Falcon 9 dominates orbital launch (private)"},{"name":"ULA","ticker":"N/A","note":"Atlas V/Vulcan (Boeing/LM JV)"}], "edge": "ONLY commercially proven small/medium orbital launch provider not named SpaceX. Neutron rocket will compete with Falcon 9 directly. Irreplaceable for DoD.", "acquirers": ["Northrop Grumman","Boeing","L3Harris"]},
    "SPIR":  {"peers": ["PL","RKLB","ASTS"], "leaders": [{"name":"Planet Labs","ticker":"PL","note":"Largest commercial satellite constellation"},{"name":"L3Harris","ticker":"LHX","note":"Geospatial intelligence for DoD"}], "edge": "Weather data from space — uniquely valuable for aviation, maritime, finance, agriculture. NRO contract validates government intelligence value.", "acquirers": ["L3Harris","Leidos","Planet Labs"]},
    "GSAT":  {"peers": ["ASTS","SPIR","PL"], "leaders": [{"name":"Iridium","ticker":"IRDM","note":"L-band satellite communications leader"},{"name":"Viasat","ticker":"VSAT","note":"Geostationary satellite broadband"}], "edge": "Apple iPhone Emergency SOS deal = guaranteed revenue. T-Mobile partnership for direct-to-cellular expanding. Spectrum assets are the real strategic value.", "acquirers": ["Apple","T-Mobile","Viasat"]},
    "MNTS":  {"peers": ["RKLB","SPIR","PL"], "leaders": [{"name":"SpaceX","ticker":"N/A","note":"Starship in-space transportation"},{"name":"Sierra Space","ticker":"N/A","note":"Dream Chaser space plane (private)"}], "edge": "In-space transportation services — moving satellites to exact orbits after launch. Critical 'last mile' logistics for satellite constellations. Only commercial player.", "acquirers": ["Rocket Lab","Northrop Grumman"]},
    "PL":    {"peers": ["SPIR","RKLB","BKSY"], "leaders": [{"name":"Maxar (private equity)","ticker":"N/A","note":"High-res commercial imagery"},{"name":"L3Harris","ticker":"LHX","note":"DoD geospatial intelligence"}], "edge": "Largest commercial Earth observation fleet (200+ satellites). Daily global coverage. Ukraine war dramatically expanded government use.", "acquirers": ["L3Harris","Leidos","ESRI"]},
    # AI DRUG
    "RXRX":  {"peers": ["SEER","ABCL","SDGR"], "leaders": [{"name":"Schrödinger","ticker":"SDGR","note":"AI drug discovery platform"},{"name":"Insilico Medicine","ticker":"N/A","note":"AI drug discovery with clinical pipeline (private)"}], "edge": "Phenomics platform generates the largest biological image dataset in existence (~30 petabytes). Sanofi+AZ+Bayer paying $150M+ for access. NVIDIA calls it 'AI biology infrastructure'.", "acquirers": ["NVIDIA","Sanofi","AstraZeneca","Pfizer"]},
    "SEER":  {"peers": ["RXRX","ABCL","OLINK"], "leaders": [{"name":"Thermo Fisher","ticker":"TMO","note":"Mass spectrometry proteomics tools"},{"name":"Illumina","ticker":"ILMN","note":"Genomics platform leader"}], "edge": "First automated unbiased proteomics system. Discovering disease biomarkers previously invisible to science. Roche/Pfizer clinical partnerships.", "acquirers": ["Thermo Fisher","Roche","Illumina","Pfizer"]},
    "ABCL":  {"peers": ["RXRX","SEER"], "leaders": [{"name":"Regeneron","ticker":"REGN","note":"Antibody discovery and development leader"},{"name":"Genentech/Roche","ticker":"RHHBY","note":"Monoclonal antibody manufacturing"}], "edge": "AI discovers antibodies from millions of immune cells. Led COVID antibody drug for Eli Lilly in record time. Platform approach: every pharma is a potential customer.", "acquirers": ["Eli Lilly","AbbVie","Merck","Genentech/Roche"]},
}

# ─────────────────────────────────────────────────────────────────────────────
# ON THE RADAR — Pre-breakout positioning plays
# ─────────────────────────────────────────────────────────────────────────────
ON_THE_RADAR = {
    "KULR": {
        "trend": "AI Infrastructure", "speculative": "moderate",
        "thesis": "NASA-certified thermal management technology pivoting from satellite/EV batteries to AI data center cooling. Phase-change materials reduce thermal runaway risk in dense GPU clusters. Sub-$200M cap with Samsung SDI and NASA partnerships.",
        "bottleneck_angle": "AI data center cooling is THE physical capacity constraint. Liquid cooling component shortages are acute — KULR's tech addresses a real gap.",
        "catalyst": "Data center pilot expansion to commercial contracts; DoD/NASA thermal management follow-ons",
        "watch_for": "Revenue ramp from data center pilots Q2-Q4 2025; enterprise thermal cooling contract announcements",
        "why_low_volume": "Market still perceives KULR as a battery company. Tiny float, no institutional coverage. Data center pivot is under-appreciated.",
        "backing": ["NASA (certified)", "Samsung SDI", "SpaceX supply chain"],
        "risk": "Early stage pivot; execution risk; capital intensive; small float",
        "asymmetric_case": "One large data center cooling contract = 3-5× from current levels",
    },
    "BKSY": {
        "trend": "Space & Satellite Intel", "speculative": "moderate",
        "thesis": "Real-time geospatial intelligence from LEO satellite constellation already providing AI-enhanced imagery and analytics to DoD and NRO. Competes directly with Planet Labs but with deeper government integration.",
        "bottleneck_angle": "Government demand for real-time space-based ISR exceeds current supply. BKSY has active NRO/DoD contracts that Wall Street has not properly valued.",
        "catalyst": "NRO contract expansion; In-Q-Tel portfolio company status; commercial government spending acceleration",
        "watch_for": "Constellation expansion milestones; revenue per satellite improving; new government contract awards",
        "why_low_volume": "Tiny market cap (~$100-200M). Overshadowed by Planet Labs. Institutional investors can't build meaningful positions without moving the stock.",
        "backing": ["DoD", "NRO", "In-Q-Tel (CIA venture arm)"],
        "risk": "Capital intensive; satellite constellation expansion requires ongoing funding; competition from PL, Maxar",
        "asymmetric_case": "NRO contract expansion or commercial data licensing deals = institutional discovery event",
    },
    "ARBE": {
        "trend": "Edge AI & Specialized Silicon", "speculative": "high",
        "thesis": "Imaging radar chipset for autonomous vehicles. Israeli company with radar pedigree from defense sector. 4D imaging radar chip provides LIDAR-like point clouds at radar's cost and reliability. Several tier-1 auto OEMs in design win pipeline.",
        "bottleneck_angle": "Autonomous vehicles need long-range, all-weather sensing. LiDAR fails in rain/fog. Radar works. ARBE's chip provides both — it's a bottleneck solution.",
        "catalyst": "Tier-1 automotive design win announcement (Denso, Continental, Bosch); major OEM SOP contract",
        "watch_for": "Production contract awards from tier-1 auto suppliers; revenue ramp from design wins Q1 2025+",
        "why_low_volume": "Sub-$100M market cap. Limited US analyst coverage. Perceived as too early-stage for institutions.",
        "backing": ["SAIC Motor", "Denso (evaluation)", "Israeli defense ecosystem"],
        "risk": "Pre-production revenue; depends on autonomous vehicle timeline; competition from Mobileye, Continental radar",
        "asymmetric_case": "Single tier-1 design win = 3-10× potential from current micro-cap levels",
    },
    "KOPN": {
        "trend": "Defense AI & Autonomy", "speculative": "moderate",
        "thesis": "Wearable display and AR optics for military headsets. Kopin's Golden-i headsets and OLED microdisplays are inside Army, Special Forces, and law enforcement AR systems. Direct beneficiary of DoD IVAS (Integrated Visual Augmentation System) ecosystem.",
        "bottleneck_angle": "The DoD's $22B IVAS headset program requires specialized microdisplays that only a handful of companies can supply — KOPN is one of them.",
        "catalyst": "IVAS production ramp by Microsoft/Army; follow-on defense AR contracts; industrial AR expansion",
        "watch_for": "IVAS headset production milestones (Microsoft + US Army); new DoD wearable display contracts",
        "why_low_volume": "IVAS program has faced delays — market has lost patience. But the program is still active and KOPN is a key supplier.",
        "backing": ["DoD", "US Army", "SOCOM", "Microsoft (IVAS prime contractor)"],
        "risk": "IVAS program risk; customer concentration; competing display technologies",
        "asymmetric_case": "IVAS production ramp begins = KOPN revenue jumps 2-3× and stock follows",
    },
    "CEVA": {
        "trend": "Edge AI & Specialized Silicon", "speculative": "low",
        "thesis": "Semiconductor IP licensing company — like ARM but for specialized AI inference, 5G, and connectivity chips. Every chip maker that uses CEVA IP pays royalties. Over 14 billion chips shipped with CEVA cores. Growing AI inference IP portfolio.",
        "bottleneck_angle": "Chip companies need AI inference IP without building it from scratch. CEVA licenses the building blocks — royalties compound with every chip shipped.",
        "catalyst": "AI inference IP adoption acceleration; new licensees adopting CEVA AI cores; royalty ramp from IoT/automotive volumes",
        "watch_for": "New AI inference IP license signings; royalty revenue per period growing; design wins from top-10 chipmakers",
        "why_low_volume": "IP licensing is a 'boring' business model — doesn't attract momentum traders. Market cap (~$300-500M) too small for large funds but too slow for retail.",
        "backing": ["Apple", "Samsung", "MediaTek", "Qualcomm ecosystem (100s of licensees)"],
        "risk": "ARM competition in some segments; longer royalty recognition cycles; revenue lumpy",
        "asymmetric_case": "AI inference IP becomes the standard in edge devices — royalties compound to 2-3× current revenue without proportional cost increase",
    },
    "BTBT": {
        "trend": "AI Infrastructure", "speculative": "high",
        "thesis": "Bit Digital is transitioning from Bitcoin mining to AI-focused GPU compute/HPC services. Already has GPU cluster customers generating AI compute revenue. One of the few bitcoin miners with a credible AI pivot story and actual paying AI compute customers.",
        "bottleneck_angle": "GPU compute is in shortage. Bitcoin miners with existing power infrastructure and GPU operations are the fastest path to additional AI compute supply.",
        "catalyst": "Large HPC/AI compute contract signing; Bitcoin mining revenue reinvested into GPU AI clusters; institutional reclassification from 'crypto' to 'AI compute'",
        "watch_for": "AI compute revenue as % of total exceeding 50%; new enterprise AI compute contracts; GPU cluster expansion announcements",
        "why_low_volume": "Still classified as a 'crypto mining' company by most screens. Institutions with ESG mandates avoid mining. AI pivot not yet priced in.",
        "backing": ["AI compute customers (undisclosed)", "HPC operators"],
        "risk": "Bitcoin price correlation; execution risk on AI pivot; competition from established cloud providers",
        "asymmetric_case": "Market re-rates from 'crypto miner' to 'AI compute provider' = 3-5× multiple expansion",
    },
    "FLUX": {
        "trend": "AI Infrastructure", "speculative": "moderate",
        "thesis": "Flux Power manufactures industrial lithium battery backup systems for forklifts and distribution centers. Pivoting into data center UPS (uninterruptible power supply) markets. Walmart, Amazon already customers. Data center power reliability is a rapidly growing segment.",
        "bottleneck_angle": "AI data centers require extreme power reliability — a 1-second outage can corrupt training runs worth millions. Battery backup systems are a critical component.",
        "catalyst": "Data center UPS contract wins; Amazon/Walmart distribution center scale-up; DOE data center backup power incentives",
        "watch_for": "Data center customer revenue; gross margin expansion with higher-value enterprise contracts; new distribution center deployment announcements",
        "why_low_volume": "Industrial battery backup is perceived as unglamorous. Market doesn't see the data center angle yet. Sub-$100M cap too small for institutions.",
        "backing": ["Walmart (customer)", "Amazon DCs (customer)", "Manufacturing sector"],
        "risk": "Competition from Eaton, Vertiv; supply chain; customer concentration",
        "asymmetric_case": "Land a data center UPS contract with a hyperscaler = institutional discovery and 3-5× move",
    },
    "LTBR": {
        "trend": "Nuclear & New Energy", "speculative": "high",
        "thesis": "Lightbridge Corporation develops next-gen nuclear fuel rod technology that claims to generate 10-30% more power from existing reactors while improving safety margins. If validated and adopted by utilities, this is a multi-billion dollar licensing opportunity without building new reactors.",
        "bottleneck_angle": "Existing US nuclear fleet (93 reactors) needs to produce more power to meet AI data center demand. Upgrading fuel rods is faster than building new reactors.",
        "catalyst": "NRC fuel qualification testing completion; first utility partnership/licensing agreement; DOE co-funding for fuel development",
        "watch_for": "NRC regulatory milestones; utility LOI or licensing discussions; DOE grant awards for fuel development",
        "why_low_volume": "Pre-revenue, regulatory-dependent timeline. Nuclear fuel R&D cycles are 5-7 years. Retail investors don't understand NRC approval process.",
        "backing": ["Centrus Energy (strategic partner)", "USNC", "DOE (funding discussions)"],
        "risk": "Pre-revenue; regulatory timeline uncertain; NRC approval process is long; competition from Westinghouse fuel",
        "asymmetric_case": "First utility licensing deal = stock could 5-10× from current nano-cap levels",
    },
    "SATL": {
        "trend": "Space & Satellite Intel", "speculative": "high",
        "thesis": "Satellogic provides high-frequency satellite imagery at low cost, operating a constellation with sub-meter resolution capability. Has active government contracts with US agencies, Argentina, Middle East. Positioned at the intersection of space intelligence and AI-driven geospatial analytics.",
        "bottleneck_angle": "Government demand for real-time, affordable satellite imagery exceeds current commercial supply. SATL can re-image any location on Earth multiple times per day at a fraction of legacy satellite costs.",
        "catalyst": "US government contract expansion; commercial data subscription growth; AI analytics platform revenue",
        "watch_for": "Revenue per satellite improving; new government contract awards; commercial subscription ARR growth",
        "why_low_volume": "Very small market cap (<$200M). Argentina HQ creates investor uncertainty. Limited US analyst coverage.",
        "backing": ["US Gov agencies", "Argentina MoD", "Middle East governments", "UN agencies"],
        "risk": "Capital intensive; competition from Planet Labs, BlackSky; geopolitical risk given non-US origin",
        "asymmetric_case": "US government adopts SATL as alternative to Planet Labs = revenue doubles and institutional investors discover",
    },
    "BFLY": {
        "trend": "AI Drug Discovery", "speculative": "moderate",
        "thesis": "Butterfly Network makes the world's first handheld, chip-based ultrasound device (iQ+) powered by AI image interpretation. FDA-cleared and CE-marked. Target markets: hospital bedside, military medical, rural/developing world healthcare. Subscription SaaS model generating recurring revenue.",
        "bottleneck_angle": "Ultrasound diagnosis requires expensive machines and trained technicians. Butterfly democratizes point-of-care diagnostics — critical for military field medicine and rural healthcare.",
        "catalyst": "DoD/military medical adoption at scale; hospital enterprise subscription growth; global health organization partnerships (WHO, MSF)",
        "watch_for": "Enterprise subscription ARR growth; military contract awards; gross margin improvement from hardware cost reduction",
        "why_low_volume": "Lost in the medtech/digital health crash of 2021-2022. Profitable path unclear to generalist investors. DARPA interest not priced in.",
        "backing": ["DARPA (medical applications research)", "Hospital systems", "WHO pilots"],
        "risk": "Path to profitability long; hardware cost still high; competition from GE, Siemens, Philips ultrasound divisions",
        "asymmetric_case": "Military field medicine adoption contract + hospital enterprise deal = revenue inflection and stock re-rating",
    },
    "LAZR": {
        "trend": "Edge AI & Specialized Silicon", "speculative": "high",
        "thesis": "Luminar Technologies makes LiDAR sensors specifically optimized for highway autonomous driving, with production-intent partnerships with Volvo, Mercedes-Benz, and others. NVIDIA partnership integrates Luminar sensors into the DRIVE Orin autonomous vehicle platform.",
        "bottleneck_angle": "Level 3+ autonomous driving requires long-range LiDAR that camera/radar cannot replace. Luminar's 250-meter range at highway speed is the enabling technology.",
        "catalyst": "Volvo EX90 production ramp with Luminar sensor; Mercedes DRIVE Pilot production scale; NVIDIA DRIVE Orin adoption by additional OEMs",
        "watch_for": "Revenue ramp from Volvo EX90 production; new OEM design win announcements; unit economics improving with scale",
        "why_low_volume": "AV timeline delays killed sentiment. Stock down 90%+ from peak. Market pricing in failure. But production contracts are still active.",
        "backing": ["Volvo (production contract)", "Mercedes-Benz", "NVIDIA (platform partner)", "Intel Mobileye (licensing)"],
        "risk": "AV timeline further delays; OEM production ramp slower than expected; cash burn; competition from Mobileye, Innoviz",
        "asymmetric_case": "Volvo EX90 production ramp begins at volume + one new top-5 OEM design win = stock recovers to 3-5× current levels",
    },
    "EVLV": {
        "trend": "Defense AI & Autonomy", "speculative": "moderate",
        "thesis": "Evolv Technology makes AI-powered security screening systems that detect weapons without requiring people to remove items or slow down (unlike metal detectors). Deployed in schools, stadiums, hospitals, and government buildings. DHS has piloted Evolv systems.",
        "bottleneck_angle": "Mass casualty event prevention at venues requires security that doesn't create bottlenecks and long queues — Evolv solves this with AI screening that processes 3,600 people/hour.",
        "catalyst": "Federal mandate for AI security screening in schools post-legislation; DHS/TSA scaled rollout; international airport adoption",
        "watch_for": "Federal contract awards; SaaS subscription ARR growth; gross margin expansion with software mix shift",
        "why_low_volume": "Security screening feels like a legacy market. AI angle under-appreciated. Stock recovered from accounting restatement — clean story now.",
        "backing": ["DHS (pilot programs)", "TSA (evaluation)", "Schools (customer)", "Stadiums and venues"],
        "risk": "Federal budget cycles slow; false positive rate perception risk; competition from Smiths Detection, Leidos screening",
        "asymmetric_case": "Federal mandate for AI security screening (active legislative discussion) = immediate addressable market 10× and stock follows",
    },
    "ONDS": {
        "trend": "Defense AI & Autonomy", "speculative": "high",
        "thesis": "Ondas Holdings develops drone automation systems for railways (American Robotics subsidiary) and critical infrastructure inspection. FAA-approved beyond-visual-line-of-sight (BVLOS) operations. DoD and DHS contracts active. Railway automation is a massive underserved market.",
        "bottleneck_angle": "Railway inspection and critical infrastructure surveillance requires autonomous drones — human inspection is too slow and too dangerous. FAA BVLOS waiver is the regulatory moat.",
        "catalyst": "BNSF or CSX nationwide drone inspection contract; DoD expansion of autonomous surveillance contracts; FAA BVLOS rule finalization",
        "watch_for": "Revenue from railway contracts growing; new BVLOS waiver grants; DoD follow-on contract awards; gross margin improving",
        "why_low_volume": "Tiny market cap (<$100M), multiple subsidiaries make it confusing, no pure-play comp. FAA regulatory complexity scares investors.",
        "backing": ["BNSF Railway (customer)", "CSX (customer)", "DoD", "DHS", "AAR (Association of American Railroads)"],
        "risk": "Pre-profitability; FAA regulatory risk; execution across multiple business lines; customer concentration",
        "asymmetric_case": "Nationwide railway inspection contract with BNSF/CSX + DoD contract expansion = revenue 5× and institutional discovery",
    },
    "UUUU": {
        "trend": "Nuclear & New Energy", "speculative": "low",
        "thesis": "Energy Fuels is the largest operating uranium mine operator in the US AND is producing rare earth elements (neodymium, praseodymium) — the same elements needed for EV motors and wind turbines. Critical mineral dual-play: nuclear fuel for AI data centers AND rare earth for energy transition. US government needs domestic supply of both.",
        "bottleneck_angle": "The US has 93 nuclear reactors needing uranium AND an EV supply chain needing rare earth magnets — and China controls 90% of global rare earth processing. UUUU is one of the only US-based solutions to both bottlenecks simultaneously.",
        "catalyst": "DOE uranium reserve purchase program; REE processing facility completing commissioning; new utility uranium supply contracts; government rare earth offtake agreements",
        "watch_for": "Revenue from uranium sales growing; REE separation facility operational; government offtake contracts for uranium and REE",
        "why_low_volume": "Uranium and rare earth are niche markets. Mining stocks are out of favor with ESG-focused institutions. Most retail investors don't understand the dual-play thesis.",
        "backing": ["DoE (uranium reserve buyer)", "DoD (critical minerals)", "Uranium utility contracts"],
        "risk": "Uranium price volatility; REE commissioning delays; mining execution risk; geopolitical risk on uranium pricing",
        "asymmetric_case": "Government critical mineral designation + utility uranium contract + REE offtake = multiple expansion from current levels",
    },
    "POWL": {
        "trend": "AI Infrastructure", "speculative": "low",
        "thesis": "Powell Industries makes custom-engineered switchgear, breakers and electrical control systems for utilities, data centers, and oil & gas. Direct beneficiary of grid build-out for AI data centers. Record backlog, accelerating bookings, expanding margins.",
        "bottleneck_angle": "Every new hyperscale data center needs medium-voltage switchgear with multi-year lead times. Powell is one of only a handful of US-based suppliers.",
        "catalyst": "Continued data center bookings; LNG export build-out; grid resilience spending; utility capex acceleration",
        "watch_for": "Backlog growth quarter-over-quarter; data center % of mix; operating margin expansion past 17%",
        "why_low_volume": "Industrial electrical equipment is unloved by growth investors. Recently re-rated but still below peers like ETN/VRT on multiples.",
        "backing": ["Major US utilities", "LNG operators", "Hyperscaler EPC partners"],
        "risk": "Cyclical capex exposure; project execution risk; commodity input costs",
        "asymmetric_case": "Backlog conversion + margin expansion = continued earnings beats; re-rating closer to VRT multiple",
    },
    "IREN": {
        "trend": "AI Infrastructure", "speculative": "high",
        "thesis": "IREN (formerly Iris Energy) operates 100% renewable-powered data centers and is rapidly pivoting capacity from Bitcoin mining to AI/HPC GPU cloud. Already deploying NVIDIA H100/H200 clusters. Owns the power, owns the land, owns the substations — the AI-compute chokepoint.",
        "bottleneck_angle": "AI compute is gated by power-connected land. IREN has secured 2.7+ GW of grid capacity — extraordinarily valuable optionality for AI cloud customers.",
        "catalyst": "AI cloud revenue ramp; new hyperscaler GPU-as-a-Service contracts; institutional reclassification away from crypto",
        "watch_for": "AI cloud ARR vs. mining revenue mix; GPU utilization rates; new enterprise AI contracts; power capacity coming online",
        "why_low_volume": "Tagged as a 'crypto miner' by screens despite real AI revenue. ESG mandates avoid mining. AI pivot still under-appreciated.",
        "backing": ["NVIDIA (GPU partner)", "Enterprise AI compute customers"],
        "risk": "Bitcoin price correlation; GPU capex intensive; hyperscaler competition; execution on AI pivot",
        "asymmetric_case": "Reclassified from crypto miner to AI compute provider = multiple-expansion re-rating of 3-5×",
    },
    "NXT": {
        "trend": "Nuclear & New Energy", "speculative": "low",
        "thesis": "Nextracker is the global leader in solar tracker systems, capturing share as utility-scale solar build-out accelerates to feed grid demand from AI data centers. Massive multi-year backlog, technology lead in bifacial/AI-optimized tracking.",
        "bottleneck_angle": "Utility-scale solar is the fastest-deployable new generation source — and trackers boost yields 20-25%. Data center PPAs are driving record solar buildout.",
        "catalyst": "Continued backlog growth; IRA tax credit extensions; international expansion; software/AI tracker margin lift",
        "watch_for": "Backlog book-to-bill ratio; international % of revenue; margin expansion from software attach",
        "why_low_volume": "Solar-adjacent stocks have been out of favor post-rate-hike cycle. Backlog quality is under-discussed.",
        "backing": ["Major IPPs", "Utility-scale developers worldwide"],
        "risk": "Solar policy risk; competition from Array Technologies; project deferral risk",
        "asymmetric_case": "Multi-year backlog conversion at expanding margins + AI data center solar demand = compound EPS growth",
    },
    "GRRR": {
        "trend": "Defense AI & Autonomy", "speculative": "high",
        "thesis": "Gorilla Technology Group provides AI-powered video analytics, smart-city infrastructure, and edge AI security platforms. Major Egyptian smart-city contract win and growing pipeline in Middle East / Asia government surveillance and infrastructure modernization.",
        "bottleneck_angle": "Governments worldwide are deploying AI video analytics for security and infrastructure. Gorilla has reference deployments giving them an edge in winning further large national contracts.",
        "catalyst": "Egypt smart-city contract execution; additional government framework deals; profitability inflection",
        "watch_for": "Revenue recognition cadence from Egypt contract; new geographic wins; gross margin trend",
        "why_low_volume": "Micro-cap, ADR with Taiwan operations creates investor confusion. Limited analyst coverage despite billion-dollar contracts.",
        "backing": ["Egypt government", "Asian municipal customers"],
        "risk": "Customer concentration (single very large contract); execution risk; geopolitical risk",
        "asymmetric_case": "Egypt contract revenue conversion + 1-2 new sovereign contracts = revenue ramp + re-rating",
    },
    "LUNR": {
        "trend": "Space & Satellite Intel", "speculative": "high",
        "thesis": "Intuitive Machines is the leading US commercial lunar lander operator, holding NASA CLPS contracts and growing services in lunar logistics, communications relay, and data services. First successful US lunar landing since Apollo (IM-1, 2024).",
        "bottleneck_angle": "NASA's Artemis program needs commercial lunar logistics partners. Only a handful of companies can deliver — LUNR has the highest TRL.",
        "catalyst": "Successful IM-2, IM-3 missions; lunar data relay contract awards; commercial customer wins beyond NASA",
        "watch_for": "Mission success rate; backlog growth; new contract awards beyond NASA",
        "why_low_volume": "Volatile stock tied to single-mission outcomes. Investors burned by IM-1 sideways landing. Long-term contract value under-appreciated.",
        "backing": ["NASA", "DoD (lunar comms studies)"],
        "risk": "Mission-failure risk; contract concentration with NASA; cash burn",
        "asymmetric_case": "Successful mission + new NASA/commercial contracts = re-rate as the lunar logistics platform",
    },
    "RDW": {
        "trend": "Space & Satellite Intel", "speculative": "moderate",
        "thesis": "Redwire Space is a pure-play space infrastructure company — solar arrays, deployable structures, in-space manufacturing, and lunar/Mars exploration hardware. Hardware is on ISS, Artemis, and most major NASA programs. Growing backlog.",
        "bottleneck_angle": "Every space mission needs structural hardware and power. Redwire's components are space-flight-proven, an enormous moat versus newcomers.",
        "catalyst": "Backlog conversion to revenue; profitability inflection; Edge Autonomy acquisition integration boosting defense exposure",
        "watch_for": "Adjusted EBITDA turning positive; backlog growth; defense % of revenue rising",
        "why_low_volume": "SPAC-era stock, post-de-SPAC overhang. Mixed hardware portfolio confuses investors despite real backlog.",
        "backing": ["NASA", "DoD", "ESA", "Commercial space stations"],
        "risk": "Profitability path; integration risk; mission timing pushing revenue out",
        "asymmetric_case": "Defense expansion + profitability = re-rating toward pure-play space infrastructure multiple",
    },
    "INDI": {
        "trend": "Edge AI & Specialized Silicon", "speculative": "moderate",
        "thesis": "indie Semiconductor designs analog/mixed-signal chips for automotive — radar, LiDAR, in-cabin sensing, and connectivity. $7B+ design-win pipeline. Pure-play on next-gen auto electronics including ADAS Level 2/3.",
        "bottleneck_angle": "Every new vehicle needs more sensing chips. indie has design wins with major OEMs that convert to revenue 2-3 years out — backlog is enormous vs. current sales.",
        "catalyst": "Design-win conversion into shipping revenue; ADAS adoption acceleration; margin expansion at scale",
        "watch_for": "Strategic backlog (design wins) growth; revenue ramp vs. backlog; gross margin trajectory",
        "why_low_volume": "Auto chip stocks out of favor; investors focused on data center AI. Backlog mechanics misunderstood.",
        "backing": ["Major auto Tier 1s and OEMs (undisclosed)"],
        "risk": "Auto cycle exposure; design-win to revenue lag; cash burn; competition from NXPI, ON",
        "asymmetric_case": "Design wins converting to revenue + margin scale = explosive earnings ramp 2026-2027",
    },
    "HIMX": {
        "trend": "Edge AI & Specialized Silicon", "speculative": "moderate",
        "thesis": "Himax Technologies makes display driver ICs and is a leading supplier of LCoS micro-displays for AR/VR glasses, including Meta and other major AR programs. Direct beneficiary of consumer AR glasses adoption cycle starting 2025-2026.",
        "bottleneck_angle": "AR/AI glasses need ultra-efficient micro-displays. Himax is one of two or three credible LCoS suppliers globally.",
        "catalyst": "Meta AR glasses production ramp; new AR/AI glasses programs from Apple/Samsung/Google; automotive display content per car rising",
        "watch_for": "Non-driver IC revenue (WLO, LCoS) growth; new AR design wins; gross margin expansion",
        "why_low_volume": "Taiwan ADR, considered cyclical display driver stock. AR/AI glasses optionality not yet in numbers.",
        "backing": ["Meta (component supplier)", "Major AR program OEMs"],
        "risk": "Cyclical display driver business; AR/AI glasses adoption uncertain; Taiwan geopolitical risk",
        "asymmetric_case": "Consumer AR glasses inflection + Himax LCoS share = revenue inflection and re-rating",
    },
    "AISP": {
        "trend": "Defense AI & Autonomy", "speculative": "high",
        "thesis": "Airship AI Holdings makes AI-powered video surveillance and edge analytics platforms used by DoD, federal law enforcement, and critical infrastructure operators. Recently won large contracts, fast-growing recurring revenue.",
        "bottleneck_angle": "DoD/DHS need AI to process the exploding volume of surveillance feeds. Airship's platform sits at this edge-AI bottleneck.",
        "catalyst": "Continued federal contract wins; commercial expansion; gross margin scale-up",
        "watch_for": "Bookings cadence; recurring revenue %; gross margin past 60%",
        "why_low_volume": "Nano-cap recent IPO; tiny float; almost no analyst coverage despite government traction.",
        "backing": ["DoD", "DHS", "Federal LEA"],
        "risk": "Nano-cap dilution risk; customer concentration; execution risk",
        "asymmetric_case": "Federal contract pipeline conversion + commercial expansion = 5-10× revenue runway",
    },
    "BE": {
        "trend": "Nuclear & New Energy", "speculative": "moderate",
        "thesis": "Bloom Energy makes solid-oxide fuel cells delivering on-site baseload power — increasingly used by AI data centers to bypass grid constraints. Recent AEP utility partnership (1 GW capacity) and hyperscaler interest validate the data center pivot.",
        "bottleneck_angle": "Hyperscale data centers can't wait years for grid upgrades. Fuel cells deploy in months. Bloom is the only US fuel cell supplier at industrial scale.",
        "catalyst": "AEP partnership conversion to orders; hyperscaler deployment announcements; profitability inflection",
        "watch_for": "Backlog growth; data center mix of revenue; positive operating margin",
        "why_low_volume": "Long history of cash burn; hydrogen narrative has soured. Data center pivot is the new story but discounted.",
        "backing": ["AEP", "Hyperscaler interest (undisclosed)", "SK ecosystem"],
        "risk": "Cash burn; natural gas price exposure; competition from gas turbines; profitability path long",
        "asymmetric_case": "Hyperscaler fuel-cell deployment contracts = revenue inflection and stock re-rating",
    },
    "VLD": {
        "trend": "Defense AI & Autonomy", "speculative": "high",
        "thesis": "Velo3D's metal 3D printing systems make complex aerospace and defense parts impossible to manufacture conventionally. SpaceX, hypersonics, and defense primes are customers. Restructured business with new management focused on defense.",
        "bottleneck_angle": "Hypersonic and rocket propulsion programs require complex metal parts that only advanced AM systems can produce. Velo3D's tech is uniquely capable.",
        "catalyst": "Defense order inflow; hypersonic program ramp; profitability inflection under new management",
        "watch_for": "New defense customer announcements; bookings growth; cash burn declining",
        "why_low_volume": "Post-SPAC nano-cap with restructuring overhang. Many investors burned and gave up despite real defense pull.",
        "backing": ["SpaceX (former customer)", "Defense primes (undisclosed)"],
        "risk": "Cash burn; customer concentration; competitive AM landscape",
        "asymmetric_case": "Defense-only pivot succeeds + hypersonic program wins = path to revenue 3-5× current",
    },
}

RADAR_TICKERS = list(ON_THE_RADAR.keys())
RADAR_TREND = {t: d["trend"] for t, d in ON_THE_RADAR.items()}


# ─────────────────────────────────────────────────────────────────────────────
# SCORING HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def get_partnership_score(ticker: str):
    p = PARTNERSHIPS.get(ticker, {})
    hs = p.get("hyperscalers", [])
    df = p.get("defense", [])
    ot = p.get("others", [])
    score = min(100, len(hs) * 14 + len(df) * 18 + len(ot) * 7)
    return score, hs, df, ot


def fetch_option_metrics(stock) -> dict:
    """Pull nearest-expiry option chain and compute call-volume signals.
    Returns dict or None if unavailable. Best-effort — wrapped by caller."""
    try:
        expiries = stock.options
        if not expiries:
            return None
        # Use nearest expiry for current-day flow signal
        chain = stock.option_chain(expiries[0])
        calls = chain.calls
        puts = chain.puts
        if calls is None or calls.empty:
            return None
        call_vol = int(calls["volume"].fillna(0).sum())
        call_oi  = int(calls["openInterest"].fillna(0).sum())
        put_vol  = int(puts["volume"].fillna(0).sum()) if puts is not None and not puts.empty else 0
        put_oi   = int(puts["openInterest"].fillna(0).sum()) if puts is not None and not puts.empty else 0
        vol_oi_ratio = (call_vol / call_oi) if call_oi > 0 else None
        put_call_ratio = (put_vol / call_vol) if call_vol > 0 else None
        # Unusual: today's call volume is large vs. its own open interest, AND skewed bullish
        unusual = (
            call_vol >= 1000 and
            vol_oi_ratio is not None and vol_oi_ratio >= 0.5 and
            (put_call_ratio is None or put_call_ratio < 0.75)
        )
        return {
            "call_volume": call_vol,
            "call_oi": call_oi,
            "put_volume": put_vol,
            "vol_oi_ratio": round(vol_oi_ratio, 2) if vol_oi_ratio is not None else None,
            "put_call_ratio": round(put_call_ratio, 2) if put_call_ratio is not None else None,
            "unusual_calls": bool(unusual),
            "nearest_expiry": expiries[0],
        }
    except Exception:
        return None


def fetch_stock_data(ticker: str, trend_override: str = None) -> dict:
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        def g(k, default=None):
            v = info.get(k, default)
            return v if v is not None else default

        market_cap    = g("marketCap", 0)
        total_cash    = g("totalCash", 0)
        total_debt    = g("totalDebt", 0)
        op_cf         = g("operatingCashflow")
        total_rev     = g("totalRevenue", 0)
        rev_growth    = g("revenueGrowth")
        gross_mgn     = g("grossMargins")
        op_mgn        = g("operatingMargins")
        r_and_d       = g("researchDevelopment")
        current_price = g("currentPrice") or g("regularMarketPrice", 0)
        wk52_high     = g("fiftyTwoWeekHigh", 0)
        wk52_low      = g("fiftyTwoWeekLow", 0)
        beta          = g("beta")
        fwd_pe        = g("forwardPE")
        pb            = g("priceToBook")
        ev            = g("enterpriseValue", 0)
        short_pct     = g("shortPercentOfFloat")
        analyst_rat   = g("recommendationMean")
        long_name     = g("longName", ticker)

        # Cash runway
        cash_runway = None
        cash_runway_label = "N/A"
        if op_cf is not None and op_cf < 0:
            monthly_burn = abs(op_cf) / 12
            if monthly_burn > 0:
                cash_runway = total_cash / monthly_burn
                cash_runway_label = f"{cash_runway:.1f}mo"
        elif op_cf is not None and op_cf >= 0:
            cash_runway = 9999
            cash_runway_label = "CF+"

        mcap_b = market_cap / 1e9 if market_cap else 0
        cash_to_mcap = (total_cash / market_cap * 100) if market_cap > 0 else 0
        net_cash = total_cash - total_debt
        net_cash_to_mcap = (net_cash / market_cap * 100) if market_cap > 0 else 0
        ev_rev = (ev / total_rev) if ev and total_rev else None
        rd_pct = (r_and_d / total_rev * 100) if r_and_d and total_rev else None
        pct_of_52wh = (current_price / wk52_high * 100) if wk52_high and current_price else None

        p_score, hs, df, ot = get_partnership_score(ticker)
        inno_score = INNOVATION_SCORES.get(ticker, 65)
        trend = trend_override or TICKER_TO_TREND.get(ticker, "Unknown")
        tam_score = SECTOR_TAM_SCORES.get(trend, 75)

        if mcap_b < 1:      mcap_score = 100
        elif mcap_b < 3:    mcap_score = 95
        elif mcap_b < 7:    mcap_score = 88
        elif mcap_b < 15:   mcap_score = 80
        elif mcap_b < 35:   mcap_score = 70
        elif mcap_b < 75:   mcap_score = 45
        else:               mcap_score = 25

        if cash_runway is None:     runway_score = 15
        elif cash_runway >= 9999:   runway_score = 100
        elif cash_runway >= 36:     runway_score = 95
        elif cash_runway >= 24:     runway_score = 88
        elif cash_runway >= 18:     runway_score = 78
        elif cash_runway >= 12:     runway_score = 65
        elif cash_runway >= 6:      runway_score = 38
        else:                       runway_score = 12

        if cash_to_mcap >= 40:   cash_score = 100
        elif cash_to_mcap >= 25: cash_score = 88
        elif cash_to_mcap >= 15: cash_score = 75
        elif cash_to_mcap >= 8:  cash_score = 58
        elif cash_to_mcap >= 3:  cash_score = 38
        else:                    cash_score = 20

        if rev_growth is None:          growth_score = 45
        elif rev_growth >= 1.0:         growth_score = 100
        elif rev_growth >= 0.6:         growth_score = 93
        elif rev_growth >= 0.4:         growth_score = 85
        elif rev_growth >= 0.25:        growth_score = 75
        elif rev_growth >= 0.15:        growth_score = 65
        elif rev_growth >= 0.05:        growth_score = 52
        elif rev_growth >= 0:           growth_score = 40
        else:                           growth_score = 22

        if gross_mgn is None:    scal_score = 45
        elif gross_mgn >= 0.80:  scal_score = 100
        elif gross_mgn >= 0.65:  scal_score = 90
        elif gross_mgn >= 0.50:  scal_score = 78
        elif gross_mgn >= 0.35:  scal_score = 63
        elif gross_mgn >= 0.20:  scal_score = 48
        else:                    scal_score = 28

        overall = (
            mcap_score   * 0.18 +
            runway_score * 0.14 +
            cash_score   * 0.10 +
            growth_score * 0.14 +
            scal_score   * 0.10 +
            p_score      * 0.12 +
            inno_score   * 0.12 +
            tam_score    * 0.10
        )

        comps = COMPS.get(ticker, {})

        # Backlog-to-market-cap ratio (forward growth/adoption signal)
        backlog_b = BACKLOG_B.get(ticker)
        backlog_to_mcap = None
        if backlog_b is not None and backlog_b > 0 and mcap_b > 0:
            backlog_to_mcap = round((backlog_b / mcap_b) * 100, 1)

        # Live options flow — best effort
        opts = fetch_option_metrics(stock) or {}

        return {
            "ticker": ticker, "trend": trend,
            "name": long_name, "sector": g("sector", "Unknown"),
            "price": round(current_price, 2) if current_price else None,
            "market_cap_b": round(mcap_b, 2), "market_cap": market_cap,
            "cash_m": round(total_cash / 1e6, 1) if total_cash else 0,
            "net_cash_m": round(net_cash / 1e6, 1) if net_cash else 0,
            "cash_to_mcap": round(cash_to_mcap, 1),
            "net_cash_to_mcap": round(net_cash_to_mcap, 1),
            "cash_runway": cash_runway_label,
            "cash_runway_raw": cash_runway,
            "revenue_growth": round(rev_growth * 100, 1) if rev_growth is not None else None,
            "gross_margin": round(gross_mgn * 100, 1) if gross_mgn is not None else None,
            "op_margin": round(op_mgn * 100, 1) if op_mgn is not None else None,
            "ev_rev": round(ev_rev, 1) if ev_rev else None,
            "rd_pct": round(rd_pct, 1) if rd_pct else None,
            "beta": round(beta, 2) if beta else None,
            "fwd_pe": round(fwd_pe, 1) if fwd_pe and fwd_pe > 0 else None,
            "pb": round(pb, 2) if pb else None,
            "short_pct": round(short_pct * 100, 1) if short_pct else None,
            "analyst_rating": round(analyst_rat, 2) if analyst_rat else None,
            "pct_of_52wh": round(pct_of_52wh, 1) if pct_of_52wh else None,
            "wk52_high": round(wk52_high, 2) if wk52_high else None,
            "wk52_low": round(wk52_low, 2) if wk52_low else None,
            "hyperscalers": hs, "defense_partners": df, "other_partners": ot,
            "mcap_score": mcap_score, "runway_score": runway_score,
            "cash_score": cash_score, "growth_score": growth_score,
            "scal_score": scal_score, "partnership_score": p_score,
            "innovation_score": inno_score, "tam_score": tam_score,
            "overall_score": round(overall, 1),
            "meets_mcap": bool(market_cap and market_cap < 35e9),
            "meets_runway": bool(cash_runway and cash_runway >= 12),
            "meets_cash": cash_to_mcap >= 8,
            "comps_peers": comps.get("peers", []),
            "comps_leaders": comps.get("leaders", []),
            "comps_edge": comps.get("edge", ""),
            "comps_acquirers": comps.get("acquirers", []),
            "backlog_b": backlog_b,
            "backlog_to_mcap": backlog_to_mcap,
            "call_volume": opts.get("call_volume"),
            "call_oi": opts.get("call_oi"),
            "put_volume": opts.get("put_volume"),
            "vol_oi_ratio": opts.get("vol_oi_ratio"),
            "put_call_ratio": opts.get("put_call_ratio"),
            "unusual_calls": opts.get("unusual_calls", False),
            "nearest_expiry": opts.get("nearest_expiry"),
            "error": None,
        }
    except Exception as e:
        return {
            "ticker": ticker,
            "trend": trend_override or TICKER_TO_TREND.get(ticker, "Unknown"),
            "overall_score": 0, "error": str(e),
        }


# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    p = Path("index.html")
    if p.exists():
        return HTMLResponse(p.read_text())
    return HTMLResponse("<h1>index.html not found</h1>")


@app.get("/api/screen")
async def screen_stocks():
    main_tickers  = list(TICKER_TO_TREND.keys())
    radar_tickers = RADAR_TICKERS

    all_tickers = list(dict.fromkeys(main_tickers + radar_tickers))

    loop = asyncio.get_event_loop()
    tasks = []
    for t in all_tickers:
        trend_ov = RADAR_TREND.get(t) if t in RADAR_TICKERS and t not in TICKER_TO_TREND else None
        tasks.append(loop.run_in_executor(executor, fetch_stock_data, t, trend_ov))

    raw = await asyncio.gather(*tasks, return_exceptions=True)

    main_results  = []
    radar_results = []
    errors = []

    for t, r in zip(all_tickers, raw):
        if isinstance(r, Exception):
            errors.append(str(r)); continue
        if r.get("error"):
            errors.append(f"{r['ticker']}: {r['error']}"); continue
        if t in RADAR_TICKERS and t not in TICKER_TO_TREND:
            meta = ON_THE_RADAR.get(t, {})
            r.update({
                "thesis": meta.get("thesis", ""),
                "bottleneck_angle": meta.get("bottleneck_angle", ""),
                "catalyst": meta.get("catalyst", ""),
                "watch_for": meta.get("watch_for", ""),
                "why_low_volume": meta.get("why_low_volume", ""),
                "backing": meta.get("backing", []),
                "risk": meta.get("risk", ""),
                "asymmetric_case": meta.get("asymmetric_case", ""),
                "speculative": meta.get("speculative", "high"),
            })
            radar_results.append(r)
        else:
            main_results.append(r)

    main_results.sort(key=lambda x: x.get("overall_score", 0), reverse=True)
    radar_results.sort(key=lambda x: x.get("overall_score", 0), reverse=True)

    trend_summaries = []
    for t_name, t_data in TRENDS.items():
        stocks = [r for r in main_results if r.get("trend") == t_name]
        trend_summaries.append({
            "name": t_name, "icon": t_data["icon"], "color": t_data["color"],
            "description": t_data["description"], "bottleneck": t_data["bottleneck"],
            "why_asymmetric": t_data["why_asymmetric"], "catalysts": t_data["catalysts"],
            "stock_count": len(stocks),
            "avg_score": round(sum(s["overall_score"] for s in stocks) / len(stocks), 1) if stocks else 0,
            "top_pick": stocks[0]["ticker"] if stocks else None,
        })

    combined = main_results + radar_results

    # High backlog/market-cap ratio (forward revenue growth/adoption signal)
    backlog_stocks = [
        r for r in combined
        if r.get("backlog_to_mcap") is not None and r.get("backlog_to_mcap") >= 30
    ]
    backlog_stocks.sort(key=lambda x: x["backlog_to_mcap"], reverse=True)

    # Unusual call volume (bullish flow — possible upward move / earnings beat signal)
    unusual_call_stocks = [r for r in combined if r.get("unusual_calls")]
    unusual_call_stocks.sort(key=lambda x: x.get("vol_oi_ratio") or 0, reverse=True)

    return JSONResponse({
        "timestamp": datetime.now().isoformat(),
        "stocks": main_results,
        "radar_stocks": radar_results,
        "backlog_stocks": backlog_stocks,
        "unusual_call_stocks": unusual_call_stocks,
        "trends": trend_summaries,
        "total_screened": len(main_tickers),
        "total_returned": len(main_results),
        "errors": errors,
    })


if __name__ == "__main__":
    import os
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")), log_level="info")
