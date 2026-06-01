import asyncio
import json
import os
import random
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import base64
import secrets
import urllib.request
import urllib.error

import uvicorn
import yfinance as yf
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response

# In-memory cache of the latest screener payload — used by the chat endpoint
# so the LLM can answer questions about whatever the user is currently viewing.
_LAST_SCREEN: dict = {}

app = FastAPI(title="Asymmetric Stock Screener")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ─────────────────────────────────────────────────────────────────────────────
# OPTIONAL HTTP BASIC AUTH (set SCREENER_PASSWORD env var to enable)
# ─────────────────────────────────────────────────────────────────────────────
_AUTH_USER = os.getenv("SCREENER_USER", "viewer")
_AUTH_PASS = os.getenv("SCREENER_PASSWORD")


@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    if not _AUTH_PASS:
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8", errors="ignore")
            user, _, pwd = decoded.partition(":")
            if (
                secrets.compare_digest(user, _AUTH_USER)
                and secrets.compare_digest(pwd, _AUTH_PASS)
            ):
                return await call_next(request)
        except Exception:
            pass
    return Response(
        status_code=401,
        content="Authentication required.",
        headers={"WWW-Authenticate": 'Basic realm="Asymmetric Stock Screener"'},
    )

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
        "tickers": ["AMBA", "LSCC", "SOUN", "CRDO", "MRVL", "NVTS", "PLAB"],
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
    "Edge Compute & Rugged AI": {
        "icon": "📡", "color": "#14b8a6",
        "description": "Ruggedized servers, mobile AI compute, and edge inference platforms deployed at the tactical, industrial, and vehicular edge — outside the hyperscale data center.",
        "bottleneck": "Centralized cloud AI cannot serve real-time tactical, industrial, and mobile workloads due to latency, bandwidth, and survivability constraints. Hardened edge compute is the only path — and only a handful of integrators can build it.",
        "why_asymmetric": "Defense, energy, transportation, and telecom all need AI inference at the edge. The total addressable market is large, but the supplier list is short — and most companies trade at small-cap multiples while serving F500 / DoD customers.",
        "catalysts": ["DoD JADC2 & CJADC2 deployment", "5G/MEC private network buildout", "Industrial robotics & autonomy", "Mobile/tactical AI inference (REPLICATOR, IVAS, NGAD)", "Edge MLOps standardization"],
        "tickers": ["OSS", "MRCY", "PENG", "DGII", "CSPI", "AEYE"],
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
    "PLAB":  {"hyperscalers": [], "defense": ["US foundries"], "others": ["TSMC", "Samsung Foundry", "GlobalFoundries", "UMC", "STMicro", "Infineon", "Onsemi"]},
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
    # Edge Compute & Rugged AI
    "OSS":   {"hyperscalers": ["NVIDIA (Elite partner)"], "defense": ["Lockheed Martin", "Raytheon", "Northrop", "US Army", "US Navy"], "others": ["Verizon", "Disguise"]},
    "MRCY":  {"hyperscalers": [], "defense": ["Lockheed Martin", "RTX", "Northrop", "BAE", "L3Harris", "DoD"], "others": ["NVIDIA", "Intel"]},
    "PENG":  {"hyperscalers": ["NVIDIA"], "defense": ["DoE labs"], "others": ["Meta (HPC)", "Stellantis", "Top semi fabs"]},
    "DGII":  {"hyperscalers": ["AWS", "Azure"], "defense": [], "others": ["AT&T", "Verizon", "Utilities", "Industrial OEMs"]},
    "CSPI":  {"hyperscalers": [], "defense": ["DoD", "US Navy"], "others": ["HPE channel", "Arrow ECS", "F500 banks"]},
    "AEYE":  {"hyperscalers": [], "defense": [], "others": ["Continental", "NVIDIA", "ITS infra (states)"]},
}

INNOVATION_SCORES = {
    "IONQ": 96, "RGTI": 91, "QBTS": 87, "QUBT": 82,
    "RXRX": 93, "ABCL": 89, "SEER": 83,
    "ASTS": 90, "RKLB": 87, "SPIR": 82, "MNTS": 84, "GSAT": 71, "PL": 79,
    "AMBA": 83, "CRDO": 84, "MRVL": 80, "LSCC": 77, "SOUN": 80, "NVTS": 82,
    "PLTR": 90, "BBAI": 84, "KTOS": 80, "AVAV": 77, "RCAT": 80, "ACHR": 87,
    "NNE": 87, "SMR": 84, "OKLO": 92, "BWXT": 74, "CEG": 67, "GEV": 77,
    "SMCI": 72, "VRT": 74, "NPWR": 82, "AEHR": 74, "LIQT": 78, "PLAB": 76,
    "CRWD": 87, "S": 84, "VRNS": 82, "CYBR": 80, "TENB": 74, "QLYS": 72,
    # Radar
    "KULR": 80, "BKSY": 79, "ARBE": 84, "KOPN": 76, "CEVA": 83,
    "BTBT": 68, "FLUX": 72, "LTBR": 86, "SATL": 77, "BFLY": 82,
    "LAZR": 85, "EVLV": 79, "ONDS": 78, "UUUU": 70,
    "POWL": 73, "IREN": 78, "NXT": 80, "GRRR": 76, "LUNR": 84,
    "RDW": 78, "INDI": 81, "HIMX": 76, "AISP": 77, "BE": 79, "VLD": 80,
    # Edge Compute & Rugged AI
    "OSS": 82, "MRCY": 78, "PENG": 80, "DGII": 70, "CSPI": 68, "AEYE": 77,
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
    "AMBA": 0.0, "LSCC": 0.0, "MRVL": 0.0, "INDI": 7.1, "CEVA": 0.0, "PLAB": 0.18,
    # Drug discovery
    "RXRX": 1.2, "ABCL": 1.5, "SEER": 0.07,
    # Radar
    "ARBE": 0.06, "GRRR": 0.10, "ONDS": 0.041, "AISP": 0.035,
    "KOPN": 0.18, "BFLY": 0.0, "LAZR": 3.4, "EVLV": 0.31, "UUUU": 0.0,
    "LTBR": 0.0, "SATL": 0.06, "KULR": 0.025, "FLUX": 0.07, "BTBT": 0.0, "VLD": 0.30,
    # Edge Compute & Rugged AI
    "OSS": 0.04, "MRCY": 1.30, "PENG": 0.65, "DGII": 0.30, "CSPI": 0.05, "AEYE": 0.05,
}

SECTOR_TAM_SCORES = {
    "Quantum Computing": 98, "AI Drug Discovery": 93, "Defense AI & Autonomy": 91,
    "AI Infrastructure": 92, "Space & Satellite Intel": 89, "Nuclear & New Energy": 89,
    "Edge AI & Specialized Silicon": 88, "Cybersecurity AI": 86,
    "Edge Compute & Rugged AI": 90,
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
    "PLAB":  {"peers": ["AEHR","KLAC","LRCX"], "leaders": [{"name":"Toppan Photomasks","ticker":"N/A","note":"Japanese photomask leader (private subsidiary of Toppan)"},{"name":"DNP Photomask","ticker":"N/A","note":"Dai Nippon Printing photomask division"},{"name":"Hoya","ticker":"HOCPY","note":"High-end EUV mask blanks supplier"}], "edge": "Only US-based merchant photomask supplier — every chip wafer requires photomasks. Critical CHIPS Act supplier, dual US fabs (Texas + Florida) make PLAB the de-risked domestic alternative to Japanese duopoly. Trades at low single-digit EV/EBITDA despite indispensable position.", "acquirers": ["Toppan","DNP","Hoya","Onto Innovation","Veeco"]},
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
    # EDGE COMPUTE & RUGGED AI
    "OSS":   {"peers": ["MRCY","CSPI","PENG"], "leaders": [{"name":"Dell Technologies","ticker":"DELL","note":"Dominant rugged/enterprise server vendor"},{"name":"Mercury Systems","ticker":"MRCY","note":"Mission-critical defense compute, $900M revenue"}], "edge": "Only NVIDIA Elite partner focused on rugged, mobile, transportable AI compute. Sub-$200M cap with multi-year DoD design wins (NGAD, REPLICATOR, Patriot) — the literal hardware that puts NVIDIA GPUs at the tactical edge.", "acquirers": ["Mercury Systems","Curtiss-Wright","Dell","Leonardo DRS"]},
    "MRCY":  {"peers": ["OSS","CSPI","KTOS"], "leaders": [{"name":"Lockheed Martin","ticker":"LMT","note":"Defense prime — Mercury sells into them"},{"name":"Curtiss-Wright","ticker":"CW","note":"Embedded defense computing competitor"},{"name":"L3Harris","ticker":"LHX","note":"Mission systems / electronic warfare"}], "edge": "Embedded mission computing for hypersonics, EW, ISR, radar. Trusted-foundry US-only fabrication = irreplaceable for classified programs. Inside virtually every modern US weapons platform.", "acquirers": ["Lockheed Martin","BAE","Curtiss-Wright","RTX"]},
    "PENG":  {"peers": ["SMCI","OSS","VRT"], "leaders": [{"name":"Dell Technologies","ticker":"DELL","note":"Largest HPC/AI server vendor"},{"name":"HP Enterprise","ticker":"HPE","note":"Cray HPC & supercomputing"}], "edge": "Penguin Solutions (the AI/HPC arm) designs and operates purpose-built AI clusters for hyperscaler-class enterprises (Meta, top semi fabs, DOE labs). Memory IP (SMART Modular) adds an AI-memory tailwind.", "acquirers": ["Dell","HPE","SK Hynix","Hitachi"]},
    "DGII":  {"peers": ["CAMP","SWIR (acq.)","CSPI"], "leaders": [{"name":"Cisco","ticker":"CSCO","note":"Industrial IoT & edge routing"},{"name":"Sierra Wireless (Semtech)","ticker":"SMTC","note":"IoT cellular modules"}], "edge": "Largest pure-play industrial IoT edge connectivity in North America. Cellular routers + edge gateways + IoT MQTT broker — sticky industrial customer base with high gross margins.", "acquirers": ["Cisco","Honeywell","Emerson","Belden"]},
    "CSPI":  {"peers": ["OSS","MRCY"], "leaders": [{"name":"Cisco","ticker":"CSCO","note":"Networking hardware giant"},{"name":"HPE","ticker":"HPE","note":"Compute and networking incumbent"}], "edge": "Myricom 10/100GbE packet-capture cards remain the gold standard for low-latency network analytics (HFT, defense, cyber). Arrow ECS distribution arm provides recurring services revenue. Trades near book value with hidden IP.", "acquirers": ["OSS","Arrow Electronics","Mercury Systems"]},
    "AEYE":  {"peers": ["INVZ","OUST","LAZR"], "leaders": [{"name":"Mobileye","ticker":"MBLY","note":"Dominant ADAS perception platform"},{"name":"Bosch","ticker":"N/A","note":"Tier-1 sensor leader (private)"}], "edge": "1500-meter LiDAR detection (vs. competitors' 250m) optimized for highway and ITS infrastructure. Continental partnership puts AEye into auto OEMs without the capex. Software-defined sensor — upgradeable post-deployment.", "acquirers": ["Continental","Mobileye","NVIDIA","Magna"]},
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
        prev_close    = g("regularMarketPreviousClose") or g("previousClose")
        day_change_pct = g("regularMarketChangePercent")
        wk52_change   = g("52WeekChange")
        wk52_high     = g("fiftyTwoWeekHigh", 0)
        wk52_low      = g("fiftyTwoWeekLow", 0)
        target_low    = g("targetLowPrice")
        target_med    = g("targetMedianPrice") or g("targetMeanPrice")
        target_high   = g("targetHighPrice")
        eps_q_growth  = g("earningsQuarterlyGrowth")
        eps_growth    = g("earningsGrowth")
        rev_q_growth  = g("revenueQuarterlyGrowth")
        ma50          = g("fiftyDayAverage")
        ma200         = g("twoHundredDayAverage")
        next_earnings_ts = g("earningsTimestamp") or g("earningsTimestampStart")
        num_analysts  = g("numberOfAnalystOpinions")
        rec_key       = g("recommendationKey")
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

        # 1-year projections: prefer analyst targets, fall back to heuristics on current price
        if current_price:
            bear_1y = round(target_low, 2)  if target_low  else round(current_price * 0.70, 2)
            base_1y = round(target_med, 2)  if target_med  else round(current_price * 1.10, 2)
            bull_1y = round(target_high, 2) if target_high else round(current_price * 1.50, 2)
            target_source = "analyst" if (target_low or target_med or target_high) else "model"
            bear_pct = round((bear_1y / current_price - 1) * 100, 1)
            base_pct = round((base_1y / current_price - 1) * 100, 1)
            bull_pct = round((bull_1y / current_price - 1) * 100, 1)
        else:
            bear_1y = base_1y = bull_1y = None
            bear_pct = base_pct = bull_pct = None
            target_source = None

        # Daily perf: deterministic compute from prev close (yfinance's pct field is unreliable)
        if prev_close and current_price:
            day_pct = round((current_price - prev_close) / prev_close * 100, 2)
        elif day_change_pct is not None:
            day_pct = round(day_change_pct * 100 if abs(day_change_pct) < 1 else day_change_pct, 2)
        else:
            day_pct = None
        wk52_change_pct = round(wk52_change * 100, 1) if wk52_change is not None else None

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
            "prev_close": round(prev_close, 2) if prev_close else None,
            "day_pct": day_pct,
            "wk52_change_pct": wk52_change_pct,
            "bear_1y": bear_1y, "base_1y": base_1y, "bull_1y": bull_1y,
            "bear_pct": bear_pct, "base_pct": base_pct, "bull_pct": bull_pct,
            "target_source": target_source,
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
            "eps_q_growth_pct": round(eps_q_growth * 100, 1) if eps_q_growth is not None else None,
            "eps_growth_pct":   round(eps_growth   * 100, 1) if eps_growth   is not None else None,
            "rev_q_growth_pct": round(rev_q_growth * 100, 1) if rev_q_growth is not None else None,
            "ma50":  round(ma50, 2)  if ma50  else None,
            "ma200": round(ma200, 2) if ma200 else None,
            "next_earnings_ts": next_earnings_ts,
            "num_analysts": num_analysts,
            "recommendation_key": rec_key,
            "error": None,
        }
    except Exception as e:
        return {
            "ticker": ticker,
            "trend": trend_override or TICKER_TO_TREND.get(ticker, "Unknown"),
            "overall_score": 0, "error": str(e),
        }


# ─────────────────────────────────────────────────────────────────────────────
# ADJACENT UNIVERSE — names in the same themes/bottlenecks but NOT yet on
# the screener or radar. Rotates daily based on a date-seeded shuffle.
# ─────────────────────────────────────────────────────────────────────────────
ADJACENT_UNIVERSE = {
    "AI Infrastructure": [
        "ANET","CIEN","COHR","FN","LITE","INFN","COMM","EXTR","RDWR","NTAP",
        "PSTG","WDC","MU","KLAC","LRCX","AMAT","ENTG","ICHR","ACMR","MKSI",
        "ONTO","POWI","MPWR","DLR","EQIX","FLEX","JBL","DELL","HPE","ETN",
    ],
    "Defense AI & Autonomy": [
        "LMT","RTX","NOC","GD","LHX","BAH","SAIC","CACI","LDOS","HEI",
        "TDG","CW","TXT","MOG.A","ESLT","ATRO","TGI","KAMN","SPCE","RDW",
        "TATT","HEI.A","CDRE","V2X","DCO",
    ],
    "Quantum Computing": [
        "IBM","GOOGL","INTC","HON","ATOM","FORM","AAOI","NVMI","MKSI","OSIS",
        "ANSS","CDNS","SNPS","ARQQ","CIFR",
    ],
    "Nuclear & New Energy": [
        "VST","EXC","AEP","D","SO","DUK","NEE","ETR","NRG","TLN",
        "UEC","CCJ","NXE","DNN","URG","LEU","BW","FLR","KBR","PRIM",
        "CWEN","ORA","PWR","MIR","TPC","CECO",
    ],
    "Edge AI & Specialized Silicon": [
        "AVGO","QCOM","MBLY","MCHP","SLAB","COHR","IPGP","ARM","SWKS","QRVO",
        "ALGM","CRUS","POWI","ON","WOLF","SITM","HLIT","AEIS","KLIC","ASTS",
        "DIOD","SMTC","RMBS",
    ],
    "Cybersecurity AI": [
        "PANW","FTNT","ZS","NET","OKTA","RPD","VRSN","GEN","DDOG","CHKP",
        "FRSH","NTNX","RBRK","CFLT","SAIL","HCP","ESTC","TWLO","BB","CGEN",
    ],
    "Space & Satellite Intel": [
        "IRDM","VSAT","LMT","NOC","BA","GD","COMM","KTOS","AAA","KARO",
        "VOXR","SATX","DCO","SARC","HEI","TDG",
    ],
    "AI Drug Discovery": [
        "SDGR","EXAI","TEM","CRNX","PACB","ILMN","TMO","A","BNTX","MRNA",
        "EXAS","NTRA","VRTX","ALNY","ARWR","RGNX","GH","NVTA","DNA","GINK",
        "VOR","RPTX","RXRX","AUR","ABSI",
    ],
    "Edge Compute & Rugged AI": [
        "VECO","ROK","AME","SMTC","IPGP","COHR","KEYS","ANET","FN","CIEN",
        "FORM","MKSI","ICHR","ULBI","ESE","GVA","NSSC","CGNX","FARO","BHE",
        "SANM","CLS","FLEX","JBL",
    ],
}


def fetch_adjacent_basic(ticker: str, trend: str) -> dict:
    """Lightweight basic-fundamentals fetch for adjacent universe — no option chains."""
    try:
        info = yf.Ticker(ticker).info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        prev  = info.get("regularMarketPreviousClose") or info.get("previousClose")
        mc    = info.get("marketCap", 0) or 0
        wk_chg = info.get("52WeekChange")
        rev_g  = info.get("revenueGrowth")
        gm     = info.get("grossMargins")
        wk_hi  = info.get("fiftyTwoWeekHigh", 0)
        beta   = info.get("beta")
        t_low  = info.get("targetLowPrice")
        t_med  = info.get("targetMedianPrice") or info.get("targetMeanPrice")
        t_high = info.get("targetHighPrice")
        day_pct = None
        if prev and price:
            day_pct = round((price - prev) / prev * 100, 2)
        pct_of_52wh = round(price / wk_hi * 100, 1) if (wk_hi and price) else None
        bear_1y = round(t_low, 2)  if t_low  else (round(price * 0.70, 2) if price else None)
        base_1y = round(t_med, 2)  if t_med  else (round(price * 1.10, 2) if price else None)
        bull_1y = round(t_high, 2) if t_high else (round(price * 1.50, 2) if price else None)
        bear_pct = round((bear_1y / price - 1) * 100, 1) if (bear_1y and price) else None
        base_pct = round((base_1y / price - 1) * 100, 1) if (base_1y and price) else None
        bull_pct = round((bull_1y / price - 1) * 100, 1) if (bull_1y and price) else None
        return {
            "ticker": ticker,
            "trend": trend,
            "name": info.get("longName", ticker),
            "sector": info.get("sector", "—"),
            "industry": info.get("industry", "—"),
            "price": round(price, 2) if price else None,
            "prev_close": round(prev, 2) if prev else None,
            "market_cap_b": round(mc / 1e9, 2) if mc else None,
            "day_pct": day_pct,
            "wk52_change_pct": round(wk_chg * 100, 1) if wk_chg is not None else None,
            "pct_of_52wh": pct_of_52wh,
            "revenue_growth": round(rev_g * 100, 1) if rev_g is not None else None,
            "gross_margin":   round(gm * 100, 1) if gm is not None else None,
            "beta": round(beta, 2) if beta else None,
            "bear_1y": bear_1y, "base_1y": base_1y, "bull_1y": bull_1y,
            "bear_pct": bear_pct, "base_pct": base_pct, "bull_pct": bull_pct,
            "target_source": "analyst" if (t_low or t_med or t_high) else "model",
        }
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# MARKET-WIDE TOP PICKS & FUNDAMENTAL PICKS (curated universes, daily rotation)
# ─────────────────────────────────────────────────────────────────────────────
TOP_PICKS_UNIVERSE = [
    # Mega-cap quality compounders
    "NVDA","MSFT","AAPL","GOOGL","META","AMZN","V","MA","COST","BRK-B",
    # AI / hyper-growth
    "AVGO","AMD","ASML","NOW","CRM","PANW","NET","NFLX","SHOP","UBER",
    "ABNB","DDOG","TSM","ANET","INTU","SPOT","ARM","SNOW",
    # Healthcare leaders
    "LLY","NVO","UNH","ISRG","REGN","VRTX",
    # Disruption / fintech
    "TSLA","HOOD","SOFI","COIN","NU","SE","MELI","MSTR","CLSK","MARA",
    # Industrial / energy quality
    "ETN","GEV","CAT","DE",
]

FUNDAMENTAL_UNIVERSE = [
    # Compounders & insurance
    "BRK-B","COST","V","MA","ADP","ROP","TMO","DHR","ITW","PGR","TRV",
    # Tech with FCF
    "ORCL","CSCO","TXN","ADI","INTU","NOW","ANET","ASML",
    # Pharma / staples value
    "PFE","MRK","ABBV","JNJ","BMY","NKE","SBUX","PEP","KO","WMT","TGT","HD","LOW","UPS","FDX",
    # Industrials value
    "EMR","HON","ETN","PH","ROK","CAT","DE","CMI",
    # Financials
    "JPM","BAC","WFC","C","MS","GS","SPGI","MCO","BLK",
]

FAVORITES_PATH = Path(__file__).parent / "favorites_archive.json"
CALL_VOLUME_ARCHIVE_PATH = Path(__file__).parent / "call_volume_archive.json"
UPSWING_ARCHIVE_PATH = Path(__file__).parent / "upswing_archive.json"
UPSWING_ARCHIVE_THRESHOLD = 30  # Only archive predictions scoring ≥ this


def _load_upswing_archive() -> dict:
    if UPSWING_ARCHIVE_PATH.exists():
        try:
            return json.loads(UPSWING_ARCHIVE_PATH.read_text())
        except Exception:
            pass
    return {"records": []}


def _save_upswing_archive(a: dict):
    UPSWING_ARCHIVE_PATH.write_text(json.dumps(a, indent=2))


def _fetch_close_on_or_after(ticker: str, target_iso: str):
    """Return (close_price, actual_date) for the first trading day on/after target_iso."""
    try:
        target = datetime.fromisoformat(target_iso).date()
        end    = target + timedelta(days=7)
        hist   = yf.Ticker(ticker).history(start=target.isoformat(), end=end.isoformat())
        if hist.empty:
            return None, None
        row = hist.iloc[0]
        return round(float(row["Close"]), 2), hist.index[0].date().isoformat()
    except Exception:
        return None, None


def update_upswing_archive(upswing_today: list) -> dict:
    """Persist any prediction scoring ≥ threshold; resolve earnings-passed records by fetching close price."""
    arch = _load_upswing_archive()
    today_iso = datetime.now().date().isoformat()
    records = arch.setdefault("records", [])
    active_by_ticker = {r["ticker"]: r for r in records if r.get("status") == "active"}

    for u in upswing_today:
        if u.get("upswing_score", 0) < UPSWING_ARCHIVE_THRESHOLD:
            continue
        t = u["ticker"]
        ed_iso = None
        if u.get("days_to_earnings") is not None and u["days_to_earnings"] >= 0:
            ed_iso = (datetime.now().date() + timedelta(days=u["days_to_earnings"])).isoformat()

        existing = active_by_ticker.get(t)
        if existing:
            existing["last_updated"] = today_iso
            existing["latest_score"] = u.get("upswing_score")
            # New earnings cycle → close old record, open a new one
            if existing.get("earnings_date") and ed_iso and ed_iso != existing["earnings_date"]:
                existing["status"] = "stale"
                existing["closed_at"] = today_iso
                existing = None
        if not existing:
            records.append({
                "id": f"{t}-{today_iso}-{len(records)}",
                "ticker": t,
                "name": u.get("name"),
                "trend": u.get("trend"),
                "first_seen": today_iso,
                "first_seen_price": u.get("price"),
                "first_seen_score": u.get("upswing_score"),
                "signals_snapshot": u.get("upswing_signals", []),
                "why_snapshot": u.get("upswing_why"),
                "earnings_date": ed_iso,
                "status": "active",
                "last_updated": today_iso,
                "latest_score": u.get("upswing_score"),
            })

    # Resolve any active records whose earnings have passed — capture close on earnings day
    for rec in records:
        if rec.get("status") != "active":
            continue
        ed = rec.get("earnings_date")
        if not ed:
            continue
        try:
            ed_date = datetime.fromisoformat(ed).date()
        except Exception:
            continue
        if (datetime.now().date() - ed_date).days >= 1 and not rec.get("earnings_close_price"):
            close_px, close_date = _fetch_close_on_or_after(rec["ticker"], ed)
            if close_px:
                rec["earnings_close_price"] = close_px
                rec["earnings_close_date"] = close_date
                rec["status"] = "resolved"

    arch["last_run"] = datetime.now().isoformat()
    _save_upswing_archive(arch)
    return arch


def _load_call_archive() -> dict:
    if CALL_VOLUME_ARCHIVE_PATH.exists():
        try:
            return json.loads(CALL_VOLUME_ARCHIVE_PATH.read_text())
        except Exception:
            pass
    return {"tickers": {}}


def _save_call_archive(a: dict):
    CALL_VOLUME_ARCHIVE_PATH.write_text(json.dumps(a, indent=2))


def update_call_volume_archive(unusual_today: list) -> dict:
    """Persist any ticker that ever showed unusual call flow + the day it first appeared."""
    arch = _load_call_archive()
    today_iso = datetime.now().date().isoformat()
    tickers_state = arch.setdefault("tickers", {})
    today_set = {r["ticker"] for r in unusual_today}

    for r in unusual_today:
        t = r["ticker"]
        info = tickers_state.get(t)
        if info is None:
            info = {
                "first_seen": today_iso,
                "first_seen_price": r.get("price"),
                "first_seen_trend": r.get("trend"),
                "first_seen_name":  r.get("name"),
                "appearance_count": 0,
            }
        info["last_seen_unusual"] = today_iso
        info["last_seen_vol_oi"]  = r.get("vol_oi_ratio")
        info["last_seen_call_vol"] = r.get("call_volume")
        info["appearance_count"]  = info.get("appearance_count", 0) + 1
        info["active"] = True
        tickers_state[t] = info

    for t, info in tickers_state.items():
        if t not in today_set:
            info["active"] = False

    arch["last_run"] = datetime.now().isoformat()
    _save_call_archive(arch)
    return arch


def _load_favorites() -> dict:
    if FAVORITES_PATH.exists():
        try:
            return json.loads(FAVORITES_PATH.read_text())
        except Exception:
            pass
    return {"adjacent_favorites": {}, "top_picks": {}, "fundamental_picks": {}}


def _save_favorites(f: dict):
    FAVORITES_PATH.write_text(json.dumps(f, indent=2))


def _score_adjacent_for_favs(r: dict) -> float:
    s = 0.0
    if r.get("day_pct") is not None:         s += max(min(r["day_pct"], 15), -5) * 1.0
    if r.get("wk52_change_pct") is not None: s += max(min(r["wk52_change_pct"], 100), -50) * 0.3
    if r.get("revenue_growth") is not None:  s += max(min(r["revenue_growth"], 80), -20) * 0.5
    if r.get("gross_margin") is not None:    s += max(min(r["gross_margin"], 90), 0)  * 0.2
    return s


def _score_fundamental(r: dict) -> float:
    s = 0.0
    if r.get("drawdown_pct"):  s += min(r["drawdown_pct"], 60) * 1.0
    if r.get("gross_margin"):  s += min(r["gross_margin"], 90) * 0.5
    if r.get("roe") is not None: s += max(min(r["roe"], 60), -20) * 0.4
    if r.get("fwd_pe") and r["fwd_pe"] > 0: s += max(0, 50 - r["fwd_pe"]) * 0.5
    if r.get("fcf_yield"):     s += min(r["fcf_yield"], 15) * 1.5
    if r.get("debt_to_equity"): s -= min(r["debt_to_equity"], 300) * 0.05
    return s


def fetch_market_basic(ticker: str, theme: str = None) -> dict:
    """Richer fetch used for Top Picks & Fundamental Picks (no option chains)."""
    try:
        info = yf.Ticker(ticker).info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        prev  = info.get("regularMarketPreviousClose") or info.get("previousClose")
        mc    = info.get("marketCap", 0) or 0
        wk_chg = info.get("52WeekChange")
        wk_hi  = info.get("fiftyTwoWeekHigh", 0)
        fwd_pe = info.get("forwardPE")
        peg    = info.get("pegRatio")
        ev_ebitda = info.get("enterpriseToEbitda")
        gm     = info.get("grossMargins")
        om     = info.get("operatingMargins")
        rev_g  = info.get("revenueGrowth")
        roe    = info.get("returnOnEquity")
        de     = info.get("debtToEquity")
        fcf    = info.get("freeCashflow")
        ev     = info.get("enterpriseValue")
        div_y  = info.get("dividendYield")
        beta   = info.get("beta")
        t_low  = info.get("targetLowPrice")
        t_med  = info.get("targetMedianPrice") or info.get("targetMeanPrice")
        t_high = info.get("targetHighPrice")
        day_pct = round((price - prev) / prev * 100, 2) if (prev and price) else None
        pct_of_52wh = round(price / wk_hi * 100, 1) if (wk_hi and price) else None
        drawdown = round(100 - pct_of_52wh, 1) if pct_of_52wh is not None else None
        fcf_yield = round(fcf / ev * 100, 2) if (fcf and ev) else None
        bear_1y = round(t_low, 2)  if t_low  else (round(price * 0.70, 2) if price else None)
        base_1y = round(t_med, 2)  if t_med  else (round(price * 1.10, 2) if price else None)
        bull_1y = round(t_high, 2) if t_high else (round(price * 1.50, 2) if price else None)
        bear_pct = round((bear_1y / price - 1) * 100, 1) if (bear_1y and price) else None
        base_pct = round((base_1y / price - 1) * 100, 1) if (base_1y and price) else None
        bull_pct = round((bull_1y / price - 1) * 100, 1) if (bull_1y and price) else None
        return {
            "ticker": ticker, "theme": theme,
            "name": info.get("longName", ticker),
            "sector": info.get("sector", "—"),
            "industry": info.get("industry", "—"),
            "price": round(price, 2) if price else None,
            "prev_close": round(prev, 2) if prev else None,
            "market_cap_b": round(mc / 1e9, 2) if mc else None,
            "day_pct": day_pct,
            "wk52_change_pct": round(wk_chg * 100, 1) if wk_chg is not None else None,
            "pct_of_52wh": pct_of_52wh,
            "drawdown_pct": drawdown,
            "fwd_pe": round(fwd_pe, 2) if (fwd_pe and fwd_pe > 0) else None,
            "peg": round(peg, 2) if peg else None,
            "ev_ebitda": round(ev_ebitda, 2) if ev_ebitda else None,
            "gross_margin": round(gm * 100, 1) if gm is not None else None,
            "op_margin": round(om * 100, 1) if om is not None else None,
            "revenue_growth": round(rev_g * 100, 1) if rev_g is not None else None,
            "roe": round(roe * 100, 1) if roe is not None else None,
            "debt_to_equity": round(de, 2) if de else None,
            "fcf_yield": fcf_yield,
            "dividend_yield": round(div_y * 100, 2) if div_y else None,
            "beta": round(beta, 2) if beta else None,
            "bear_1y": bear_1y, "base_1y": base_1y, "bull_1y": bull_1y,
            "bear_pct": bear_pct, "base_pct": base_pct, "bull_pct": bull_pct,
            "target_source": "analyst" if (t_low or t_med or t_high) else "model",
        }
    except Exception:
        return None


def _top_pick_rationale(r: dict) -> str:
    parts = []
    if r.get("revenue_growth") is not None:  parts.append(f"rev growth {r['revenue_growth']}%")
    if r.get("gross_margin") is not None:    parts.append(f"GM {r['gross_margin']}%")
    if r.get("wk52_change_pct") is not None: parts.append(f"52W {r['wk52_change_pct']}%")
    if r.get("market_cap_b") is not None:    parts.append(f"${r['market_cap_b']}B cap")
    return " · ".join(parts) or "Market-leading franchise"


def _fundamental_rationale(r: dict) -> str:
    parts = []
    if r.get("drawdown_pct"):  parts.append(f"-{r['drawdown_pct']}% from 52W high")
    if r.get("fwd_pe"):        parts.append(f"FwdPE {r['fwd_pe']}")
    if r.get("fcf_yield"):     parts.append(f"FCF yield {r['fcf_yield']}%")
    if r.get("roe") is not None: parts.append(f"ROE {r['roe']}%")
    if r.get("gross_margin"):  parts.append(f"GM {r['gross_margin']}%")
    return " · ".join(parts) or "Quality compounder at discount"


def pick_adjacent_for_today(per_trend: int = 5) -> list:
    seed = datetime.now().date().toordinal()
    rnd = random.Random(seed)
    excluded = set(TICKER_TO_TREND.keys()) | set(RADAR_TICKERS)
    picks = []
    for trend, candidates in ADJACENT_UNIVERSE.items():
        pool = [t for t in candidates if t not in excluded]
        rnd.shuffle(pool)
        for t in pool[:per_trend]:
            picks.append((t, trend))
    return picks


# ─────────────────────────────────────────────────────────────────────────────
# SCREENER HISTORY (persisted) — drives "New to Screener" + "Off Screener"
# ─────────────────────────────────────────────────────────────────────────────
HISTORY_PATH = Path(__file__).parent / "screener_history.json"
NEW_TO_SCREENER_DAYS = 30


def _load_history() -> dict:
    if HISTORY_PATH.exists():
        try:
            return json.loads(HISTORY_PATH.read_text())
        except Exception:
            pass
    return {"tickers": {}}


def _save_history(h: dict):
    HISTORY_PATH.write_text(json.dumps(h, indent=2))


def update_screener_history(main_results: list) -> dict:
    """Reconcile the current screener universe against persisted history.
    Returns the updated history dict (also written to disk)."""
    h = _load_history()
    today = datetime.now().date().isoformat()
    tickers_state = h.setdefault("tickers", {})
    current = {r["ticker"]: r for r in main_results}

    for tkr, rec in current.items():
        info = tickers_state.get(tkr)
        if info is None:
            info = {
                "first_seen": today,
                "first_seen_price": rec.get("price"),
                "first_seen_trend": rec.get("trend"),
            }
        info["last_seen"] = today
        info["last_seen_price"] = rec.get("price")
        info["last_trend"] = rec.get("trend")
        info["active"] = True
        tickers_state[tkr] = info

    # Mark any previously-active ticker now missing from universe as off-screener
    for tkr, info in tickers_state.items():
        if tkr in current:
            continue
        if info.get("active"):
            info["active"] = False
            info["exit_date"] = today
            info["exit_price"] = info.get("last_seen_price")

    h["last_run"] = datetime.now().isoformat()
    _save_history(h)
    return h


def fetch_price_only(ticker: str) -> dict:
    """Lightweight live-price fetch for off-screener performance tracking."""
    try:
        info = yf.Ticker(ticker).info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        prev = info.get("regularMarketPreviousClose") or info.get("previousClose")
        dpct = info.get("regularMarketChangePercent")
        if prev and price:
            day_pct = round((price - prev) / prev * 100, 2)
        elif dpct is not None:
            day_pct = round(dpct * 100 if abs(dpct) < 1 else dpct, 2)
        else:
            day_pct = None
        return {"ticker": ticker, "price": round(price, 2) if price else None,
                "name": info.get("longName", ticker), "day_pct": day_pct}
    except Exception as e:
        return {"ticker": ticker, "price": None, "name": ticker, "day_pct": None, "error": str(e)}


def _days_between(a: str, b: str) -> int:
    try:
        return (datetime.fromisoformat(b).date() - datetime.fromisoformat(a).date()).days
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# AI-MANAGED MOCK PORTFOLIO ($100k, seeded from screener's strongest signals)
# ─────────────────────────────────────────────────────────────────────────────
AI_PORTFOLIO_PATH = Path(__file__).parent / "ai_portfolio.json"
AI_PORTFOLIO_BUDGET = 100_000.0

# Each entry is (target dollar allocation, conviction rationale tied to screener logic)
AI_PORTFOLIO_SEED = [
    ("PLTR", 7500, "Defense AI platform pure-play. Backlog grows with every DoD program; impossible for primes to replicate in-house."),
    ("KTOS", 6000, "Affordable attritable drones — REPLICATOR-aligned. Margin re-rating as Valkyrie scales."),
    ("VRT",  7000, "Liquid cooling + power distribution at every hyperscaler. Multi-year backlog. AI capex pure-play with industrial margins."),
    ("CRDO", 5500, "Active electrical cables = the 'last inch' of every AI cluster. Sole-sourced into 800G/1.6T hyperscaler builds."),
    ("OSS",  4500, "Sub-$200M cap rugged-AI compute house, NVIDIA Elite partner. Asymmetric tactical-edge bet."),
    ("MRCY", 5000, "Embedded mission compute inside every modern weapon platform. Re-rating post turnaround."),
    ("OKLO", 6000, "Aurora fast-reactor with Sam Altman as chair — hyperscaler nuclear is the AI power story. LOI pipeline >$14B vs ~$5B cap."),
    ("SMR",  4500, "Only NRC-approved SMR in the US. First-mover regulatory moat."),
    ("NNE",  3500, "Microreactor optionality for remote data centers and FOBs. Speculative but uncorrelated to large nukes."),
    ("RKLB", 6000, "Only credible non-SpaceX orbital provider. Neutron flight = the re-rate event."),
    ("ASTS", 6500, "Direct-to-cell satellite — 5.9B addressable users, carrier-funded. Sat constellation milestones drive narrative."),
    ("IONQ", 4500, "Trapped-ion gate fidelity leader. Native on all three hyperscaler clouds."),
    ("RGTI", 3000, "Modular superconducting — second-derivative quantum bet hedging IONQ's approach."),
    ("CRWD", 5500, "AI-native security at scale. Sticky 24M+ agent footprint, RPO grows linearly with cloud spend."),
    ("S",    3500, "Autonomous SOC = the labor-arbitrage thesis. Smaller cap, faster grower than CRWD."),
    ("RXRX", 4500, "AI biology infrastructure — pharma must rent the model. NVIDIA-validated, multi-pharma cash flows."),
    ("AMBA", 3500, "Edge vision-AI silicon at 10% of NVIDIA's power draw — automotive/security camera moat."),
    ("INDI", 3500, "$7B design-win backlog vs ~$500M cap. Auto chip backlog mechanics are the under-priced angle."),
    ("POWL", 4000, "Switchgear chokepoint for every new data center. Backlog accelerating, margins expanding."),
    ("BE",   3000, "Fuel cells deploy in months — hyperscalers can't wait for grid upgrades. AEP partnership is the proof point."),
]


def _build_price_map(main_results, radar_results, off_results):
    pm = {}
    for r in main_results + radar_results:
        if r.get("price"):
            pm[r["ticker"]] = {
                "price": r["price"],
                "prev_close": r.get("prev_close"),
                "day_pct": r.get("day_pct"),
                "name": r.get("name"),
                "trend": r.get("trend"),
            }
    for r in off_results:
        if r.get("current_price"):
            pm.setdefault(r["ticker"], {})
            pm[r["ticker"]].update({
                "price": r["current_price"],
                "day_pct": r.get("day_pct"),
                "name": r.get("name"),
                "trend": r.get("first_seen_trend"),
            })
    return pm


def _seed_ai_portfolio(price_map):
    today = datetime.now().date().isoformat()
    positions = []
    for ticker, dollars, rationale in AI_PORTFOLIO_SEED:
        info = price_map.get(ticker)
        if not info or not info.get("price"):
            continue
        shares = round(dollars / info["price"], 4)
        positions.append({
            "ticker": ticker,
            "shares": shares,
            "entry_price": info["price"],
            "entry_date": today,
            "target_dollars": dollars,
            "rationale": rationale,
            "trend": info.get("trend"),
        })
    invested = sum(p["shares"] * p["entry_price"] for p in positions)
    cash = round(AI_PORTFOLIO_BUDGET - invested, 2)
    portfolio = {
        "name": "AI-Managed Portfolio",
        "manager": "Claude (Asymmetric Screener AI)",
        "philosophy": "Concentrated bets on companies sitting at structural bottlenecks identified by the screener. Equal-conviction sizing within trends, weighted across all major themes. Cash reserve for adds on dislocations.",
        "inception_date": today,
        "starting_value": AI_PORTFOLIO_BUDGET,
        "positions": positions,
        "cash": cash,
        "change_log": [{"date": today, "note": "Portfolio inception — seeded from screener top signals."}],
    }
    AI_PORTFOLIO_PATH.write_text(json.dumps(portfolio, indent=2))
    return portfolio


def _load_or_seed_ai_portfolio(price_map):
    if AI_PORTFOLIO_PATH.exists():
        try:
            return json.loads(AI_PORTFOLIO_PATH.read_text())
        except Exception:
            pass
    return _seed_ai_portfolio(price_map)


def _compute_portfolio_perf(portfolio, price_map):
    rows = []
    total_value = portfolio.get("cash", 0.0)
    total_day_pl = 0.0
    total_cost = 0.0
    for p in portfolio.get("positions", []):
        info = price_map.get(p["ticker"], {})
        price = info.get("price")
        prev = info.get("prev_close")
        cost = p["shares"] * p["entry_price"]
        value = p["shares"] * price if price else cost
        day_change = p["shares"] * (price - prev) if (price and prev) else 0.0
        total_value += value
        total_day_pl += day_change
        total_cost += cost
        pl_pct = round((value - cost) / cost * 100, 2) if cost else 0.0
        rows.append({
            **p,
            "current_price": round(price, 2) if price else None,
            "current_value": round(value, 2),
            "cost_basis": round(cost, 2),
            "pl_dollars": round(value - cost, 2),
            "pl_pct": pl_pct,
            "day_pct": info.get("day_pct"),
            "day_pl_dollars": round(day_change, 2),
        })
    start_val = portfolio.get("starting_value", AI_PORTFOLIO_BUDGET)
    pre_today = total_value - total_day_pl
    return {
        **{k: v for k, v in portfolio.items() if k != "positions"},
        "positions": rows,
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_pl": round(total_value - start_val, 2),
        "total_return_pct": round((total_value - start_val) / start_val * 100, 2),
        "day_pl": round(total_day_pl, 2),
        "day_pct": round(total_day_pl / pre_today * 100, 2) if pre_today else 0.0,
        "invested_pct": round(total_cost / start_val * 100, 1) if start_val else 0.0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# UPSWING PREDICTION ENGINE — scores every ticker on 8 catalyst signals
# ─────────────────────────────────────────────────────────────────────────────
def compute_upswing_score(r: dict) -> dict:
    """Return a 0-100 score plus the list of contributing signal labels."""
    signals = []
    score = 0.0
    price = r.get("price")

    # 1. Analyst upside vs current — uses median target price
    base_1y = r.get("base_1y")
    base_pct = r.get("base_pct")
    if price and base_pct is not None and r.get("target_source") == "analyst":
        if base_pct >= 50:
            score += 18; signals.append({"label": f"🎯 Analyst upside {base_pct}%", "weight": 18, "kind": "target"})
        elif base_pct >= 25:
            score += 12; signals.append({"label": f"🎯 Analyst upside {base_pct}%", "weight": 12, "kind": "target"})
        elif base_pct >= 10:
            score += 6;  signals.append({"label": f"🎯 Analyst upside {base_pct}%", "weight": 6,  "kind": "target"})

    # 2. Quarterly EPS growth acceleration (earnings beats / strong recent print)
    eps_q = r.get("eps_q_growth_pct")
    if eps_q is not None:
        if eps_q >= 100:
            score += 14; signals.append({"label": f"📈 EPS Q growth +{eps_q}%", "weight": 14, "kind": "earnings"})
        elif eps_q >= 30:
            score += 9;  signals.append({"label": f"📈 EPS Q growth +{eps_q}%", "weight": 9,  "kind": "earnings"})
        elif eps_q >= 10:
            score += 4;  signals.append({"label": f"📈 EPS Q growth +{eps_q}%", "weight": 4,  "kind": "earnings"})
        elif eps_q < -20:
            score -= 6;  signals.append({"label": f"⚠️ EPS Q decline {eps_q}%", "weight": -6, "kind": "earnings"})

    # 3. Quarterly revenue acceleration
    rev_q = r.get("rev_q_growth_pct")
    if rev_q is not None and rev_q >= 25:
        score += 8; signals.append({"label": f"💰 Rev Q growth +{rev_q}%", "weight": 8, "kind": "revenue"})
    elif rev_q is not None and rev_q >= 10:
        score += 4; signals.append({"label": f"💰 Rev Q growth +{rev_q}%", "weight": 4, "kind": "revenue"})

    # 4. Price momentum vs moving averages (golden-cross-like setup)
    ma50  = r.get("ma50")
    ma200 = r.get("ma200")
    if price and ma50 and ma200:
        if price > ma50 > ma200:
            score += 10; signals.append({"label": "🚀 Price > 50d > 200d MA", "weight": 10, "kind": "momentum"})
        elif price > ma50 and price > ma200:
            score += 5;  signals.append({"label": "↗️ Above both MAs", "weight": 5, "kind": "momentum"})
        elif price < ma50 and price < ma200:
            score -= 4;  signals.append({"label": "↘️ Below both MAs", "weight": -4, "kind": "momentum"})

    # 5. Unusual call flow already detected
    if r.get("unusual_calls"):
        voi = r.get("vol_oi_ratio")
        score += 14; signals.append({"label": f"📞 Unusual call flow (Vol/OI {voi}×)", "weight": 14, "kind": "options"})

    # 6. Short squeeze potential — high short% + positive momentum
    short_pct = r.get("short_pct")
    day_pct = r.get("day_pct")
    if short_pct is not None and short_pct >= 15:
        if day_pct is not None and day_pct > 0:
            score += 10; signals.append({"label": f"🔥 Squeeze setup ({short_pct}% short)", "weight": 10, "kind": "squeeze"})
        else:
            score += 4;  signals.append({"label": f"🔥 High short interest {short_pct}%", "weight": 4, "kind": "squeeze"})

    # 7. Earnings imminent — within next 14 days
    days_to_earnings = None
    ts = r.get("next_earnings_ts")
    if ts:
        try:
            ev = datetime.fromtimestamp(ts)
            delta_days = (ev.date() - datetime.now().date()).days
            if 0 <= delta_days <= 14:
                days_to_earnings = delta_days
                score += 8; signals.append({"label": f"📅 Earnings in {delta_days}d", "weight": 8, "kind": "catalyst"})
            elif -3 <= delta_days < 0:
                days_to_earnings = delta_days
                score += 6; signals.append({"label": f"📅 Just reported ({-delta_days}d ago)", "weight": 6, "kind": "catalyst"})
            else:
                days_to_earnings = delta_days
        except Exception:
            pass

    # 8. Analyst consensus BUY / STRONG BUY
    rec = (r.get("recommendation_key") or "").lower()
    n_analysts = r.get("num_analysts") or 0
    if rec in ("strong_buy",) and n_analysts >= 5:
        score += 8; signals.append({"label": f"⭐ Strong Buy ({n_analysts} analysts)", "weight": 8, "kind": "analyst"})
    elif rec in ("buy",) and n_analysts >= 5:
        score += 5; signals.append({"label": f"⭐ Buy ({n_analysts} analysts)", "weight": 5, "kind": "analyst"})

    # 9. Strong 52W trend (multi-bagger setup continuing)
    wk52 = r.get("wk52_change_pct")
    if wk52 is not None and wk52 >= 100:
        score += 5; signals.append({"label": f"📊 52W +{wk52}%", "weight": 5, "kind": "trend"})

    # 10. Pullback from highs (mean-reversion setup)
    pct_of_high = r.get("pct_of_52wh")
    if pct_of_high is not None and 70 <= pct_of_high <= 90 and (wk52 is None or wk52 > 0):
        score += 4; signals.append({"label": f"🎢 Pullback to {pct_of_high}% of 52WH", "weight": 4, "kind": "setup"})

    score = max(0, min(100, round(score, 1)))

    # Build a one-line "why" summary
    if not signals:
        why = "No strong catalyst signals detected."
    else:
        top = sorted(signals, key=lambda s: abs(s["weight"]), reverse=True)[:3]
        why = " · ".join(s["label"] for s in top)

    return {
        "upswing_score": score,
        "upswing_signals": signals,
        "upswing_why": why,
        "days_to_earnings": days_to_earnings,
    }


# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────
def _compute_optimal_play(
    price, ma50, ma200, wk52_high, wk52_low, wk52_change_pct,
    beta, fwd_pe, trailing_pe, ev_rev, revenue_growth, op_margin, gross_margin,
    short_pct, market_cap_b, recommendation_mean, analyst_count,
    bear_1y, base_1y, day_pct, target_source
):
    """
    Compute an optimal play recommendation: entry strategy, key levels,
    chart signals to watch, and options plays — all with written reasoning.
    """
    if not price or price <= 0:
        return None

    def pf(p): return round(p, 2) if p else None
    def pp(p): return f"${p:.2f}" if p else "N/A"
    def pct_from(p): return round((p / price - 1) * 100, 1) if p else None

    # ── derived signals ──
    above_ma50  = price > ma50  if ma50  else None
    above_ma200 = price > ma200 if ma200 else None
    pct_off_52h = round((price / wk52_high - 1) * 100, 1) if wk52_high else None  # negative = below high
    pct_off_52l = round((price / wk52_low  - 1) * 100, 1) if wk52_low  else None  # positive = above low

    rg    = revenue_growth  # percent e.g. 25.0
    om    = op_margin
    beta  = beta or 1.0
    sp    = short_pct or 0
    rm    = recommendation_mean  # 1=strong buy, 5=strong sell

    is_large_cap = market_cap_b and market_cap_b >= 50
    is_profitable = om is not None and om > 0
    has_pe = fwd_pe and 3 < fwd_pe < 500

    # Momentum score: combine MA posture, 52W position, analyst stance
    momentum_pts = 0
    if above_ma50  is True:  momentum_pts += 2
    if above_ma200 is True:  momentum_pts += 2
    if pct_off_52h and pct_off_52h > -10: momentum_pts += 2   # near highs
    if pct_off_52h and pct_off_52h < -30: momentum_pts -= 2   # extended dip
    if rm and rm <= 2.0: momentum_pts += 2
    if rm and rm >= 3.5: momentum_pts -= 1
    if wk52_change_pct and wk52_change_pct > 30: momentum_pts += 1

    # Valuation score: how expensive vs peers/growth
    val_score = "fair"
    if has_pe and rg:
        peg = fwd_pe / rg if rg > 0 else None
        if peg and peg < 0.8:   val_score = "cheap"
        elif peg and peg < 1.5: val_score = "fair"
        else:                    val_score = "stretched"
    elif has_pe:
        val_score = "cheap" if fwd_pe < 15 else "fair" if fwd_pe < 30 else "stretched"

    # ── ENTRY STANCE ──
    if pct_off_52h is None:
        stance = "partial"
        entry_size = "50%"
        entry_action = "Take a 50% starter position at current prices."
        entry_reason = "Insufficient price history to assess entry quality; use a partial position."
    elif pct_off_52h > -5 and momentum_pts >= 4:
        stance = "partial"
        entry_size = "30–40%"
        entry_action = f"Start a 30–40% position at current prices (${price:.2f})."
        entry_reason = (
            f"The stock is within {abs(pct_off_52h):.1f}% of its 52-week high — "
            f"{'above' if above_ma50 else 'below'} the 50-day MA (${ma50:.2f}) — indicating strong momentum. "
            f"Taking a partial position captures the trend while leaving room to add on any pullback. "
            + (f"Analyst consensus is bullish ({analyst_count} analysts, mean {rm:.1f})." if rm and rm <= 2.5 else "")
        )
    elif pct_off_52h and -20 <= pct_off_52h <= -5 and above_ma50:
        stance = "buy"
        entry_size = "50–75%"
        entry_action = f"Take a 50–75% position at current prices (${price:.2f})."
        entry_reason = (
            f"The stock has pulled back {abs(pct_off_52h):.1f}% from its 52-week high but remains above the "
            f"50-day MA (${ma50:.2f}), suggesting the dip is healthy consolidation rather than trend breakdown. "
            + (f"Valuation is {val_score} — " +
               (f"forward P/E of {fwd_pe:.0f}× with {rg:.0f}% revenue growth is " +
                ("attractive." if val_score == "cheap" else "reasonable." if val_score == "fair" else "elevated but justified by growth.")
               if has_pe and rg else
               "multiple metrics support a constructive view.")
            )
        )
    elif pct_off_52h and -35 <= pct_off_52h < -20 and above_ma200:
        stance = "accumulate"
        entry_size = "75%"
        entry_action = f"Take a 75% position at current prices (${price:.2f}) — near deeper support."
        entry_reason = (
            f"Down {abs(pct_off_52h):.1f}% from the 52-week high, the stock is testing the 200-day MA "
            f"(${ma200:.2f}), a historically reliable long-term support level. "
            + ("High short interest ({:.0f}% of float) creates a potential squeeze dynamic on any positive catalyst.".format(sp) if sp >= 12 else
               "This level has historically attracted institutional buying if the fundamental thesis remains intact.")
        )
    elif above_ma200 is False and pct_off_52h and pct_off_52h < -35:
        stance = "wait"
        entry_size = "0–25%"
        entry_action = f"Hold off — wait for stabilisation above the 200-day MA (${ma200:.2f}) before committing capital."
        entry_reason = (
            f"The stock is {abs(pct_off_52h):.1f}% below its 52-week high and trading below the 200-day MA — "
            f"a classic distribution signal. A 25% speculative starter is acceptable only if the "
            f"fundamental thesis remains intact and you can tolerate further drawdown. "
            + (f"The bear analyst target (${bear_1y}) implies the market already prices in continued weakness." if bear_1y else "")
        )
    else:
        stance = "partial"
        entry_size = "50%"
        entry_action = f"Take a 50% starter position at current prices (${price:.2f})."
        entry_reason = (
            f"Mixed signals: "
            + (f"{'above' if above_ma50 else 'below'} 50-day MA (${ma50:.2f}), " if ma50 else "")
            + (f"{'above' if above_ma200 else 'below'} 200-day MA (${ma200:.2f})." if ma200 else "")
            + " A partial position manages risk while maintaining exposure to any upside catalyst."
        )

    # ── KEY PRICE LEVELS ──
    levels = []
    levels.append({
        "type": "current",
        "price": pf(price),
        "label": f"Current Price ({entry_size} entry)",
        "note": entry_action,
    })
    if ma50 and abs(price - ma50) / price > 0.01:
        levels.append({
            "type": "add" if above_ma50 else "watch",
            "price": pf(ma50),
            "label": f"50-Day MA — {'Add on pullback' if above_ma50 else 'Key resistance to reclaim'}",
            "note": (
                f"The 50-day MA (${ma50:.2f}) is {abs(pct_from(ma50)):.1f}% "
                f"{'below' if above_ma50 else 'above'} current price. "
                + ("A dip to this level is a high-probability add opportunity — this MA has contained corrections in the current trend." if above_ma50
                   else "Reclaiming the 50-day MA on volume would confirm trend recovery and is a tactical entry signal.")
            ),
        })
    if ma200 and abs(price - ma200) / price > 0.02:
        levels.append({
            "type": "full_add" if above_ma200 else "watch",
            "price": pf(ma200),
            "label": f"200-Day MA — {'Full position on deep dip' if above_ma200 else 'Critical support to hold'}",
            "note": (
                f"The 200-day MA (${ma200:.2f}) is {abs(pct_from(ma200)):.1f}% "
                f"{'below' if above_ma200 else 'above'} current price — the long-term trend line. "
                + ("A pullback here, if fundamentals are intact, is a full-position opportunity." if above_ma200
                   else "A close below the 200-day MA on volume would be a bearish structural break — reduce exposure.")
            ),
        })
    # Analyst base target as a level
    if base_1y and target_source == "analyst":
        levels.append({
            "type": "target",
            "price": pf(base_1y),
            "label": f"Analyst Median Target (${base_1y:.2f})",
            "note": f"Street consensus median is ${base_1y:.2f} — consider taking partial profits ({'+' if base_1y > price else ''}{pct_from(base_1y):.1f}%) near this level and re-evaluating the thesis.",
        })
    # Stop loss
    stop = round(ma200 * 0.95, 2) if ma200 else round(price * 0.82, 2)
    levels.append({
        "type": "stop",
        "price": stop,
        "label": f"Stop Loss / Thesis Invalidation — ${stop:.2f}",
        "note": (
            f"A decisive close below ${stop:.2f} "
            + (f"(5% below 200-day MA) " if ma200 else f"(~18% drawdown) ")
            + f"would invalidate the near-term thesis. Consider a hard stop or reduce to a watch position."
        ),
    })

    # ── CHART SIGNALS TO WATCH ──
    signals = []
    if above_ma50 and above_ma200:
        signals.append({"type": "bullish", "text":
            f"Price is above both the 50-day (${ma50:.2f}) and 200-day (${ma200:.2f}) MAs — "
            f"a 'golden cross' posture. Trend is intact. Watch for a pullback to the 50-day as the next add level."
        })
    elif above_ma50 is False and above_ma200:
        signals.append({"type": "caution", "text":
            f"Price has broken below the 50-day MA (${ma50:.2f}) but holds the 200-day (${ma200:.2f}). "
            f"This is a yellow flag — watch for a reclaim of the 50-day on volume as a recovery signal."
        })
    elif above_ma200 is False:
        signals.append({"type": "bearish", "text":
            f"Price is below the 200-day MA (${ma200:.2f}) — long-term trend is broken. "
            f"Avoid adding until a confirmed reclaim. Watch for a 'dead cat bounce' trap."
        })

    if pct_off_52h and pct_off_52h > -3:
        signals.append({"type": "watch", "text":
            f"Trading within {abs(pct_off_52h):.1f}% of the 52-week high (${wk52_high:.2f}). "
            f"A clean breakout above this level on above-average volume would be a strong continuation signal — watch for the setup."
        })

    if beta >= 1.8:
        signals.append({"type": "watch", "text":
            f"Beta of {beta:.1f} means the stock moves ~{beta:.1f}× the broader market. "
            f"In a market selloff, expect amplified drawdowns — size your position accordingly and avoid margin."
        })

    if sp >= 10:
        signals.append({"type": "watch", "text":
            f"Short interest is {sp:.1f}% of float. A positive catalyst (earnings beat, contract win, guidance raise) "
            f"could trigger a short squeeze — watch for spikes in volume on up days as shorts cover."
        })

    if day_pct and abs(day_pct) > 4:
        signals.append({"type": "watch", "text":
            f"Stock moved {day_pct:+.1f}% today — elevated single-day volatility. "
            f"Wait for intraday stabilisation before entering; a gap-fill pullback in the following session is common."
        })

    # ── OPTIONS PLAYS ──
    options = []
    high_beta = beta >= 1.5
    very_high_beta = beta >= 2.0
    bullish_bias = rm and rm <= 2.5
    neutral_bias = rm and 2.5 < rm <= 3.5

    if bullish_bias or stance in ("buy", "accumulate"):
        # CSP for premium collection while waiting
        csp_strike = pf(round((ma50 or price * 0.93) * 0.97, 2))
        options.append({
            "strategy": "Sell Cash-Secured Put (CSP)",
            "structure": f"Sell {csp_strike} put, 30–45 DTE",
            "rationale": (
                f"Sell a put at ${csp_strike} — near the 50-day MA support — to collect premium "
                f"while effectively bidding for shares at a level you'd want to own them. "
                f"If assigned, your cost basis is below the current price. "
                + (f"Beta of {beta:.1f} means elevated IV, so premium will be richer than lower-beta peers." if high_beta else
                   "Works best when IV is elevated (post-earnings, macro volatility windows).")
            ),
            "risk": "medium",
            "type": "income",
        })

    if bullish_bias and high_beta:
        # Bull call spread for defined-risk directional
        spread_buy = pf(round(price * 1.02, 2))
        spread_sell = pf(round(base_1y * 0.97 if base_1y else price * 1.20, 2))
        options.append({
            "strategy": "Bull Call Spread",
            "structure": f"Buy {spread_buy} call / Sell {spread_sell} call, 60–90 DTE",
            "rationale": (
                f"Defined-risk directional bet on a move toward the analyst median target (${base_1y:.2f}). "
                f"Buying the ATM call and selling the {spread_sell} call reduces the cost of the trade vs. a naked long call. "
                f"Max profit if stock reaches ${spread_sell} by expiry. "
                + (f"With beta {beta:.1f}, short-term IV is frequently elevated — the spread structure helps absorb IV decay." if very_high_beta else "")
            ),
            "risk": "medium",
            "type": "directional",
        })

    if stance in ("buy", "partial") and not very_high_beta:
        # Covered call if already long
        cc_strike = pf(round((base_1y * 0.95 if base_1y else price * 1.10), 2))
        options.append({
            "strategy": "Covered Call (if long shares)",
            "structure": f"Sell {cc_strike} call against existing shares, 30–45 DTE",
            "rationale": (
                f"If you already hold shares, selling a call at ${cc_strike} "
                f"({'near analyst median' if base_1y else '~10% above current price'}) "
                f"generates income and effectively lowers your cost basis. "
                f"Accept assignment if the stock rips through — it means the thesis played out."
            ),
            "risk": "low",
            "type": "income",
        })

    if very_high_beta and not bullish_bias:
        # Iron condor for neutral/uncertain high-vol stock
        ic_put_sell  = pf(round(price * 0.90, 2))
        ic_put_buy   = pf(round(price * 0.84, 2))
        ic_call_sell = pf(round(price * 1.10, 2))
        ic_call_buy  = pf(round(price * 1.16, 2))
        options.append({
            "strategy": "Iron Condor (Neutral / High-IV)",
            "structure": f"Sell {ic_put_sell}/{ic_put_buy} put spread + Sell {ic_call_sell}/{ic_call_buy} call spread, 30–45 DTE",
            "rationale": (
                f"With beta {beta:.1f} and no strong directional bias, an iron condor profits if the stock stays "
                f"between ${ic_put_sell} and ${ic_call_sell} (a ±10% range). "
                f"High beta implies rich IV — the premium collected is elevated. "
                f"Best deployed when IV rank is above 50%."
            ),
            "risk": "medium",
            "type": "neutral",
        })

    if sp >= 12 and bullish_bias:
        # Long call for squeeze play
        call_strike = pf(round(price * 1.05, 2))
        options.append({
            "strategy": "Long Call — Short Squeeze Play",
            "structure": f"Buy {call_strike} call, 45–60 DTE",
            "rationale": (
                f"Short interest of {sp:.1f}% of float sets up a potential squeeze on any positive catalyst. "
                f"A long call captures that asymmetric upside with limited defined downside (premium paid). "
                f"Size small — this is a speculative overlay on a fundamental position, not a standalone trade."
            ),
            "risk": "high",
            "type": "speculative",
        })

    # Protective put if near high / high beta
    if stance == "partial" and very_high_beta and pct_off_52h and pct_off_52h > -8:
        pp_strike = pf(round(ma50 * 0.98 if ma50 else price * 0.90, 2))
        options.append({
            "strategy": "Protective Put (Hedge)",
            "structure": f"Buy {pp_strike} put, 60–90 DTE",
            "rationale": (
                f"Near 52-week highs with beta {beta:.1f} — buying a put at ${pp_strike} "
                f"(near 50-day MA) insures the position against a sharp breakdown. "
                f"Think of it as paying for peace of mind on a momentum stock near resistance. "
                f"Cost: typically 2–4% of notional for 60 DTE."
            ),
            "risk": "low",
            "type": "hedge",
        })

    return {
        "entry": {
            "stance":        stance,
            "size":          entry_size,
            "action":        entry_action,
            "reasoning":     entry_reason,
            "val_score":     val_score,
            "momentum_pts":  momentum_pts,
        },
        "levels":  levels,
        "signals": signals,
        "options": options,
    }


def _compute_internal_projections(
    price, fwd_pe, trailing_pe, revenue_growth, gross_margin, op_margin,
    ev_rev, market_cap_b, short_pct, beta, eps_growth, peg_ratio,
    total_rev_b, total_cash_b, total_debt_b, wk52_change_pct
):
    """
    Build fundamental + speculative 1-year price projections with written reasoning.
    Returns a dict consumed by the search panel frontend.
    """
    if not price or price <= 0:
        return None

    rg   = revenue_growth  # percent, e.g. 25.0
    gm   = gross_margin    # percent, e.g. 65.0
    om   = op_margin       # percent, e.g. 12.0
    pe   = fwd_pe
    ev_r = ev_rev
    mc   = market_cap_b or 0

    is_profitable   = om is not None and om > 0
    has_rev_growth  = rg is not None
    has_pe          = pe  is not None and pe > 0 and pe < 500  # ignore nonsensical values
    has_ev_rev      = ev_r is not None and ev_r > 0

    # ── choose methodology ──
    # Use pe_beat_miss only when we have a valid forward P/E (3 < pe < 500)
    has_valid_pe = has_pe and pe > 3
    if has_valid_pe:
        method = "pe_beat_miss"
    elif has_ev_rev and has_rev_growth:
        method = "ev_revenue"
    elif has_rev_growth:
        method = "revenue_heuristic"
    else:
        method = "price_heuristic"

    # ── helper ──
    def pct(p): return round((p / price - 1) * 100, 1)

    # ────────────────────────────────────────────────────────────────────────────
    if method == "pe_beat_miss":
        # Beat/miss vs consensus framework.
        # The current price already implies what the market expects in EPS:
        #   implied_eps = price / fwd_pe
        # We then model bear (big miss + PE de-rate), base (small beat, flat PE),
        # bull (strong beat + PE expansion).
        implied_eps = price / pe
        pe_floor = max(10, round(pe * 0.55, 1))   # severe de-rating floor
        pe_ceil  = round(pe * 1.35, 1)             # expansion ceiling

        bear_eps = implied_eps * 0.70   # 30% EPS miss vs consensus
        base_eps = implied_eps * 1.06   # 6% beat — modest outperformance
        bull_eps = implied_eps * 1.22   # 22% beat — strong execution

        bear_p = round(bear_eps * pe_floor, 2)
        # Bear-case floor: lower-PE value stocks have smaller realistic drawdowns
        bear_floor = 0.78 if pe < 15 else 0.70 if pe < 25 else 0.62
        bear_p = max(bear_p, round(price * bear_floor, 2))
        base_p = round(base_eps * pe, 2)
        bull_p = round(bull_eps * pe_ceil, 2)
        bull_p = max(bull_p, round(price * 1.20, 2))   # floor: min +20%

        rule_of_40 = (rg or 0) + (om or 0)
        r40_note = (
            f"Rule of 40 = {rule_of_40:.0f} (strong)." if rule_of_40 >= 40
            else f"Rule of 40 = {rule_of_40:.0f} (improving)." if rule_of_40 >= 25
            else f"Rule of 40 = {rule_of_40:.0f} — below target."
        )
        peg_note = (
            f" PEG ratio {peg_ratio:.2f} ({'attractive' if peg_ratio < 1 else 'fair' if peg_ratio < 2 else 'stretched'})."
            if peg_ratio and peg_ratio > 0 else ""
        )
        rg_str = f"{rg:.0f}% YoY" if rg is not None else "unavailable"
        om_str = f"{om:.1f}%" if om is not None else "N/A"

        methodology_note = (
            f"Methodology: Beat/Miss vs Consensus (Forward P/E framework). "
            f"Current fwd P/E: {pe:.0f}×, implied EPS: ${implied_eps:.2f}. "
            f"Revenue growth: {rg_str}, operating margin: {om_str}. {r40_note}{peg_note}"
        )
        bear_reason = (
            f"EPS misses consensus by ~30% (implied EPS ${implied_eps:.2f} → actual ${bear_eps:.2f}), "
            f"driven by revenue deceleration{(' to ~' + str(round(rg*0.4,0)) + '%') if rg else ''} or margin compression. "
            f"Market re-rates the multiple from {pe:.0f}× down to {pe_floor:.0f}× "
            f"({'a –' + str(round((1-pe_floor/pe)*100)) + '% de-rating'}) as growth-premium justification erodes. "
            + ("High short interest ({:.0f}% of float) amplifies the selling on any miss.".format(short_pct)
               if short_pct and short_pct >= 15
               else f"Operating leverage cuts both ways — margin compression accelerates the EPS shortfall.")
        )
        base_reason = (
            f"EPS beats consensus by ~6% (${base_eps:.2f} vs implied ${implied_eps:.2f}), "
            f"consistent with modest execution outperformance. "
            f"P/E holds at {pe:.0f}× — the market continues to pay a growth premium. "
            + (f"Operating margin of {om:.1f}% provides a cushion for earnings leverage."
               if is_profitable else "Revenue execution stays on track; profitability runway remains intact.")
        )
        bull_reason = (
            f"EPS beats consensus by ~22% (${bull_eps:.2f} vs implied ${implied_eps:.2f}), "
            f"driven by{(' accelerating revenue (' + str(round(rg*1.3,0)) + '%)' + ',') if rg else ''} "
            f"margin expansion, or guidance raised. "
            f"P/E expands from {pe:.0f}× to {pe_ceil:.0f}× (+35%) as the earnings power thesis "
            f"is validated by institutional investors. "
            + (f"At {om:.1f}% operating margin, each additional point of scale generates outsized EPS leverage."
               if is_profitable else "Margin inflection toward profitability triggers a re-rating from 'growth' to 'growth + earnings' multiple.")
        )

    elif method == "ev_revenue":
        rg_d = rg / 100
        r40  = rg + (om or 0)

        # EV/Revenue beat/miss framework for pre-profit companies:
        # Bear: revenue misses by ~35%, EV/Rev contracts 45%
        # Base: revenue meets expectations, EV/Rev holds
        # Bull: revenue beats by ~55%, EV/Rev expands 50%
        bear_p = round(price * (1 + rg_d * 0.35) * 0.55, 2)
        bear_p = max(bear_p, round(price * 0.60, 2))  # floor: max –40% in one year
        base_p = round(price * (1 + rg_d * 0.90),     2)  # slight moderation baked in
        bull_p = round(price * (1 + rg_d * 1.55) * 1.50, 2)
        bull_p = max(bull_p, round(price * 1.25, 2))
        bear_evr = round(ev_r * 0.55, 1);  bull_evr = round(ev_r * 1.50, 1)

        gm_note = (f" Gross margin of {gm:.0f}% shows clear path to operating leverage at scale."
                   if gm and gm >= 60 else
                   f" Gross margin of {gm:.0f}% needs improvement for profitability." if gm else "")
        methodology_note = (
            f"Methodology: EV/Revenue multiple model (pre-profit growth company). "
            f"Current EV/Rev: {ev_r:.1f}×, revenue growth: {rg:.0f}% YoY. "
            f"Rule of 40 = {r40:.0f}.{gm_note}"
        )
        bear_reason = (
            f"Revenue growth slows to ~{rg*0.30:.0f}% and the market loses patience with the path "
            f"to profitability. EV/Revenue contracts from {ev_r:.1f}× to {bear_evr:.1f}× — "
            f"consistent with how comparable pre-profit companies re-rate on deceleration. "
            + ("High short interest means a miss triggers outsized selling." if short_pct and short_pct >= 12
               else "Cash burn risk could force a dilutive equity raise, capping upside.")
        )
        base_reason = (
            f"Revenue growth holds at {rg:.0f}% YoY. EV/Revenue stays at {ev_r:.1f}× — "
            f"the market continues paying this multiple for this growth rate. "
            + (f"Gross margin of {gm:.0f}% provides a visible path to profitability, "
               f"keeping the multiple supported." if gm and gm >= 55
               else "Execution on the current roadmap keeps the valuation intact.")
        )
        bull_reason = (
            f"Revenue growth reaccelerates to ~{rg*1.70:.0f}% through new partnerships, "
            f"contract wins, or market expansion. EV/Revenue re-rates to {bull_evr:.1f}× as "
            f"the profitability timeline becomes visible to institutional investors. "
            + (f"Gross margins of {gm:.0f}% at scale imply high-quality earnings — "
               f"re-rating from pre-profit to profitable company adds another leg up."
               if gm and gm >= 60 else "A strategic partnership announcement could be the institutional discovery catalyst.")
        )

    elif method == "revenue_heuristic":
        rg_d = rg / 100
        bear_p = round(price * (1 + rg_d * 0.25), 2)
        base_p = round(price * (1 + rg_d * 0.80), 2)
        bull_p = round(price * (1 + rg_d * 1.50), 2)
        methodology_note = (
            f"Methodology: Revenue momentum model. Revenue growth: {rg:.0f}% YoY. "
            f"P/E and EV/Revenue unavailable; price implied by growth rate scenarios."
        )
        bear_reason  = f"Growth momentum stalls at {rg*0.25:.0f}% — well below the current {rg:.0f}% run rate. Market discount widens."
        base_reason  = f"Revenue growth moderates to ~{rg*0.80:.0f}%, sustaining the current valuation multiple."
        bull_reason  = f"Revenue growth sustains near {rg:.0f}% or accelerates, driving a re-rating of the multiple."

    else:
        bear_p = round(price * 0.72, 2)
        base_p = round(price * 1.10, 2)
        bull_p = round(price * 1.45, 2)
        methodology_note = (
            "Methodology: Heuristic price model — insufficient financial data for quantitative modeling. "
            "Scenarios based on typical small/mid-cap equity return distributions."
        )
        bear_reason  = "Macro headwinds, sector rotation, or company-specific execution risk. Limited data prevents deeper quantitative analysis."
        base_reason  = "Modest appreciation in line with broad equity market + any fundamental improvement."
        bull_reason  = "Positive catalyst (earnings beat, partnership, contract win) closes the gap to intrinsic value."

    fundamental = {
        "model":            method,
        "methodology_note": methodology_note,
        "bear": {"price": bear_p, "pct": pct(bear_p), "reasoning": bear_reason},
        "base": {"price": base_p, "pct": pct(base_p), "reasoning": base_reason},
        "bull": {"price": bull_p, "pct": pct(bull_p), "reasoning": bull_reason},
    }

    # ── Speculative / asymmetric upside (3-year horizon) ──
    speculative = None
    if mc > 0 and mc < 75 and has_rev_growth and rg and rg >= 15:
        yrs = 3
        # Project revenue CAGR, then apply a terminal multiple
        # Low mc + high growth = potential 3-5× asymmetric
        cagr = rg / 100
        # Conservative: growth decelerates each year by 20%
        proj_rev_mult = (1 + cagr) * (1 + cagr * 0.8) * (1 + cagr * 0.6)
        # Multiple: if pre-profit, use current EV/Rev; if profitable, use P/E with margin improvement
        if has_pe:
            # Earnings grow faster than revenue due to op leverage
            eps_cagr = cagr * (1.3 if is_profitable else 0.9)
            sp_mult = 1.20  # modest P/E expansion over 3 years
            spec_p  = round(price * (1 + eps_cagr)**yrs * sp_mult, 2)
            spec_r  = (
                f"Three-year horizon: if revenue grows at {rg:.0f}%→{rg*0.8:.0f}%→{rg*0.6:.0f}% "
                f"(decelerating but sustained) and P/E expands 20% as earnings quality improves, "
                f"the stock reaches ${spec_p}. "
                f"Market cap would be ~${mc * (spec_p/price):.1f}B — still well within the range of "
                f"comparable mature-stage comps in this sector. "
                f"Key risks: multiple compression, execution shortfall, macro shock."
            )
        elif has_ev_rev:
            spec_p  = round(price * proj_rev_mult * 1.40, 2)  # revenue growth + re-rating
            spec_r  = (
                f"Three-year horizon: revenue grows at a decelerating CAGR (~{rg:.0f}%→{rg*0.6:.0f}%) "
                f"and EV/Revenue re-rates from {ev_r:.1f}× to ~{ev_r*1.4:.1f}× as profitability becomes "
                f"visible. Stock reaches ${spec_p} — implying a ${mc*(spec_p/price):.1f}B market cap. "
                f"Requires: no equity dilution, gross margin expansion, and at least one major "
                f"contract/partnership announcement that brings institutional coverage."
            )
        else:
            spec_p  = round(price * (1 + cagr)**yrs, 2)
            spec_r  = (
                f"Simple revenue CAGR projection over 3 years at {rg:.0f}% growth rate. "
                f"Assumes stable multiple — upside or downside depends heavily on whether "
                f"profitability milestones are met."
            )
        speculative = {
            "price":     spec_p,
            "pct":       pct(spec_p),
            "timeframe": "3-year",
            "reasoning": spec_r,
        }

    return {"fundamental": fundamental, "speculative": speculative}


@app.get("/api/ticker-suggest")
async def ticker_suggest(q: str = ""):
    """Proxy Yahoo Finance symbol search for autocomplete."""
    q = q.strip()
    if not q:
        return JSONResponse([])
    try:
        url = (
            "https://query1.finance.yahoo.com/v1/finance/search"
            f"?q={urllib.parse.quote(q)}&quotesCount=8&newsCount=0"
            "&enableFuzzyQuery=false&quotesQueryId=tss_match_phrase_query"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        results = [
            {
                "ticker": item.get("symbol", ""),
                "name":   item.get("shortname") or item.get("longname", ""),
                "type":   item.get("quoteType", ""),
                "exchange": item.get("exchDisp", ""),
            }
            for item in data.get("quotes", [])
            if item.get("symbol") and item.get("quoteType") in ("EQUITY", "ETF", "MUTUALFUND", "INDEX", "CURRENCY", "CRYPTOCURRENCY")
        ][:8]
        return JSONResponse(results)
    except Exception:
        return JSONResponse([])


@app.get("/api/search/{ticker}")
async def search_ticker(ticker: str):
    """Full data fetch for the search panel — works for ANY ticker, not just screener universe."""
    ticker = ticker.upper().strip()
    try:
        loop = asyncio.get_event_loop()
        stock  = yf.Ticker(ticker)
        info   = await loop.run_in_executor(executor, lambda: stock.info)
        if not info or (not info.get("regularMarketPrice") and not info.get("currentPrice")):
            return JSONResponse({"error": f"No data found for '{ticker}'. Check the symbol and try again."}, status_code=404)

        def g(k, default=None):
            v = info.get(k, default)
            return v if v is not None else default

        price      = g("currentPrice") or g("regularMarketPrice")
        prev_close = g("regularMarketPreviousClose") or g("previousClose")
        day_pct    = round((price - prev_close) / prev_close * 100, 2) if price and prev_close else None
        wk52_chg   = g("52WeekChange")
        wk52_high  = g("fiftyTwoWeekHigh")
        wk52_low   = g("fiftyTwoWeekLow")
        market_cap = g("marketCap", 0)
        total_cash = g("totalCash", 0)
        total_debt = g("totalDebt", 0)
        op_cf      = g("operatingCashflow")
        total_rev  = g("totalRevenue", 0)
        ev         = g("enterpriseValue", 0)
        target_low = g("targetLowPrice")
        target_med = g("targetMedianPrice") or g("targetMeanPrice")
        target_high= g("targetHighPrice")

        if price:
            bear_1y = round(target_low,  2) if target_low  else round(price * 0.70, 2)
            base_1y = round(target_med,  2) if target_med  else round(price * 1.10, 2)
            bull_1y = round(target_high, 2) if target_high else round(price * 1.50, 2)
            bear_pct = round((bear_1y / price - 1) * 100, 1)
            base_pct = round((base_1y / price - 1) * 100, 1)
            bull_pct = round((bull_1y / price - 1) * 100, 1)
            target_source = "analyst" if (target_low or target_med or target_high) else "model"
        else:
            bear_1y = base_1y = bull_1y = bear_pct = base_pct = bull_pct = None
            target_source = None

        cash_runway_label = "N/A"
        if op_cf is not None and op_cf < 0:
            monthly_burn = abs(op_cf) / 12
            if monthly_burn > 0:
                runway = total_cash / monthly_burn
                cash_runway_label = f"{runway:.1f} mo"
        elif op_cf is not None and op_cf >= 0:
            cash_runway_label = "CF+ (profitable)"

        rev_growth = g("revenueGrowth")
        gross_mgn  = g("grossMargins")
        op_mgn     = g("operatingMargins")
        r_and_d    = g("researchDevelopment")
        short_pct  = g("shortPercentOfFloat")
        fwd_pe     = g("forwardPE")
        trail_pe   = g("trailingPE")
        pb         = g("priceToBook")
        eps_growth = g("earningsGrowth")
        peg_ratio  = g("pegRatio")

        rg_pct  = round(rev_growth * 100, 1) if rev_growth  else None
        gm_pct  = round(gross_mgn  * 100, 1) if gross_mgn   else None
        om_pct  = round(op_mgn     * 100, 1) if op_mgn      else None
        sp_pct  = round(short_pct  * 100, 1) if short_pct   else None
        ev_r    = round(ev / total_rev, 1)    if ev and total_rev else None
        mc_b    = round(market_cap / 1e9, 2)  if market_cap else None
        rev_b   = round(total_rev  / 1e9, 3)  if total_rev  else None
        cash_b  = round(total_cash / 1e9, 3)  if total_cash else None
        debt_b  = round(total_debt / 1e9, 3)  if total_debt else None

        ma50_v  = round(g("fiftyDayAverage"),      2) if g("fiftyDayAverage")      else None
        ma200_v = round(g("twoHundredDayAverage"), 2) if g("twoHundredDayAverage") else None

        projections = _compute_internal_projections(
            price       = price,
            fwd_pe      = round(fwd_pe,   1) if fwd_pe  else None,
            trailing_pe = round(trail_pe, 1) if trail_pe else None,
            revenue_growth = rg_pct,
            gross_margin   = gm_pct,
            op_margin      = om_pct,
            ev_rev         = ev_r,
            market_cap_b   = mc_b,
            short_pct      = sp_pct,
            beta           = g("beta"),
            eps_growth     = round(eps_growth * 100, 1) if eps_growth else None,
            peg_ratio      = round(peg_ratio, 2) if peg_ratio and 0 < peg_ratio < 100 else None,
            total_rev_b    = rev_b,
            total_cash_b   = cash_b,
            total_debt_b   = debt_b,
            wk52_change_pct= round(wk52_chg * 100, 1) if wk52_chg else None,
        )

        optimal_play = _compute_optimal_play(
            price              = price,
            ma50               = ma50_v,
            ma200              = ma200_v,
            wk52_high          = wk52_high,
            wk52_low           = wk52_low,
            wk52_change_pct    = round(wk52_chg * 100, 1) if wk52_chg else None,
            beta               = g("beta"),
            fwd_pe             = round(fwd_pe, 1) if fwd_pe else None,
            trailing_pe        = round(trail_pe, 1) if trail_pe else None,
            ev_rev             = ev_r,
            revenue_growth     = rg_pct,
            op_margin          = om_pct,
            gross_margin       = gm_pct,
            short_pct          = sp_pct,
            market_cap_b       = mc_b,
            recommendation_mean= g("recommendationMean"),
            analyst_count      = g("numberOfAnalystOpinions"),
            bear_1y            = bear_1y,
            base_1y            = base_1y,
            day_pct            = day_pct,
            target_source      = target_source,
        )

        # Screener-universe extras
        trend      = TICKER_TO_TREND.get(ticker)
        comps_data = COMPS.get(ticker)
        radar_data = ON_THE_RADAR.get(ticker)
        partners   = PARTNERSHIPS.get(ticker)

        return JSONResponse({
            "ticker":         ticker,
            "name":           g("longName", ticker),
            "summary":        g("longBusinessSummary", ""),
            "sector":         g("sector"),
            "industry":       g("industry"),
            "website":        g("website"),
            "employees":      g("fullTimeEmployees"),
            "country":        g("country"),
            "price":          round(price, 2) if price else None,
            "day_pct":        day_pct,
            "wk52_change_pct":round(wk52_chg * 100, 1) if wk52_chg else None,
            "wk52_high":      wk52_high,
            "wk52_low":       wk52_low,
            "pct_of_52wh":    round(price / wk52_high * 100, 1) if price and wk52_high else None,
            "beta":           g("beta"),
            "market_cap_b":   round(market_cap / 1e9, 2) if market_cap else None,
            "fwd_pe":         round(fwd_pe, 1) if fwd_pe else None,
            "trailing_pe":    round(trail_pe, 1) if trail_pe else None,
            "pb":             round(pb, 2) if pb else None,
            "ev_rev":         round(ev / total_rev, 1) if ev and total_rev else None,
            "revenue_growth": round(rev_growth * 100, 1) if rev_growth else None,
            "gross_margin":   round(gross_mgn * 100, 1) if gross_mgn else None,
            "op_margin":      round(op_mgn * 100, 1) if op_mgn else None,
            "rd_pct":         round(r_and_d / total_rev * 100, 1) if r_and_d and total_rev else None,
            "short_pct":      round(short_pct * 100, 1) if short_pct else None,
            "cash_runway":    cash_runway_label,
            "dividend_yield": round(g("dividendYield") * 100, 2) if g("dividendYield") else None,
            "ma50":           ma50_v,
            "ma200":          ma200_v,
            "bear_1y":        bear_1y, "base_1y": base_1y, "bull_1y": bull_1y,
            "bear_pct":       bear_pct,"base_pct": base_pct,"bull_pct": bull_pct,
            "target_source":  target_source,
            "analyst_count":  g("numberOfAnalystOpinions"),
            "recommendation": g("recommendationKey"),
            "recommendation_mean": g("recommendationMean"),
            "in_screener":    ticker in TICKER_TO_TREND,
            "in_radar":       ticker in ON_THE_RADAR,
            "trend":          trend,
            "comps":          comps_data,
            "radar":          radar_data,
            "partnerships":   partners,
            "projections":    projections,
            "optimal_play":   optimal_play,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/info/{ticker}")
async def ticker_info(ticker: str):
    """On-demand company info for the Thesis / Projections / Optimal Play tabs."""
    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(executor, lambda: yf.Ticker(ticker).info)
        if not info:
            return JSONResponse({"error": "No info"}, status_code=404)

        def g(k, default=None):
            v = info.get(k, default)
            return v if v is not None else default

        t_low   = g("targetLowPrice")
        t_med   = g("targetMedianPrice") or g("targetMeanPrice")
        t_high  = g("targetHighPrice")
        price   = g("currentPrice") or g("regularMarketPrice")
        prev_close = g("regularMarketPreviousClose") or g("previousClose")
        day_pct = round((price - prev_close) / prev_close * 100, 2) if price and prev_close else None

        fwd_pe    = g("forwardPE")
        trail_pe  = g("trailingPE")
        rev_growth= g("revenueGrowth")
        gross_mgn = g("grossMargins")
        op_mgn    = g("operatingMargins")
        short_pct = g("shortPercentOfFloat")
        market_cap= g("marketCap", 0)
        total_rev = g("totalRevenue", 0)
        ev        = g("enterpriseValue", 0)
        eps_growth= g("earningsGrowth")
        peg_ratio = g("pegRatio")
        total_cash= g("totalCash", 0)
        total_debt= g("totalDebt", 0)
        wk52_chg  = g("52WeekChange")
        wk52_high = g("fiftyTwoWeekHigh")
        wk52_low  = g("fiftyTwoWeekLow")
        ma50_v    = round(g("fiftyDayAverage"),      2) if g("fiftyDayAverage")      else None
        ma200_v   = round(g("twoHundredDayAverage"), 2) if g("twoHundredDayAverage") else None

        rg_pct  = round(rev_growth * 100, 1) if rev_growth  else None
        gm_pct  = round(gross_mgn  * 100, 1) if gross_mgn   else None
        om_pct  = round(op_mgn     * 100, 1) if op_mgn      else None
        sp_pct  = round(short_pct  * 100, 1) if short_pct   else None
        ev_r    = round(ev / total_rev, 1)    if ev and total_rev else None
        mc_b    = round(market_cap / 1e9, 2)  if market_cap else None
        rev_b   = round(total_rev  / 1e9, 3)  if total_rev  else None
        cash_b  = round(total_cash / 1e9, 3)  if total_cash else None
        debt_b  = round(total_debt / 1e9, 3)  if total_debt else None

        target_source = "analyst" if (t_low or t_med or t_high) else "model"
        if price:
            bear_1y = round(t_low,  2) if t_low  else round(price * 0.70, 2)
            base_1y = round(t_med,  2) if t_med  else round(price * 1.10, 2)
            bull_1y = round(t_high, 2) if t_high else round(price * 1.50, 2)
        else:
            bear_1y = base_1y = bull_1y = None

        projections = _compute_internal_projections(
            price          = price,
            fwd_pe         = round(fwd_pe,   1) if fwd_pe  else None,
            trailing_pe    = round(trail_pe, 1) if trail_pe else None,
            revenue_growth = rg_pct,
            gross_margin   = gm_pct,
            op_margin      = om_pct,
            ev_rev         = ev_r,
            market_cap_b   = mc_b,
            short_pct      = sp_pct,
            beta           = g("beta"),
            eps_growth     = round(eps_growth * 100, 1) if eps_growth else None,
            peg_ratio      = round(peg_ratio, 2) if peg_ratio and 0 < peg_ratio < 100 else None,
            total_rev_b    = rev_b,
            total_cash_b   = cash_b,
            total_debt_b   = debt_b,
            wk52_change_pct= round(wk52_chg * 100, 1) if wk52_chg else None,
        ) if price else None

        optimal_play = _compute_optimal_play(
            price              = price,
            ma50               = ma50_v,
            ma200              = ma200_v,
            wk52_high          = wk52_high,
            wk52_low           = wk52_low,
            wk52_change_pct    = round(wk52_chg * 100, 1) if wk52_chg else None,
            beta               = g("beta"),
            fwd_pe             = round(fwd_pe, 1) if fwd_pe else None,
            trailing_pe        = round(trail_pe, 1) if trail_pe else None,
            ev_rev             = ev_r,
            revenue_growth     = rg_pct,
            op_margin          = om_pct,
            gross_margin       = gm_pct,
            short_pct          = sp_pct,
            market_cap_b       = mc_b,
            recommendation_mean= g("recommendationMean"),
            analyst_count      = g("numberOfAnalystOpinions"),
            bear_1y            = bear_1y,
            base_1y            = base_1y,
            day_pct            = day_pct,
            target_source      = target_source,
        ) if price else None

        return JSONResponse({
            "ticker":        ticker,
            "name":          g("longName", ticker),
            "summary":       g("longBusinessSummary", ""),
            "sector":        g("sector"),
            "industry":      g("industry"),
            "website":       g("website"),
            "employees":     g("fullTimeEmployees"),
            "city":          g("city"),
            "state":         g("state"),
            "country":       g("country"),
            "price":         round(price, 2) if price else None,
            "day_pct":       day_pct,
            "ma50":          ma50_v,
            "ma200":         ma200_v,
            "target_low":    round(t_low, 2)  if t_low  else None,
            "target_median": round(t_med, 2)  if t_med  else None,
            "target_high":   round(t_high, 2) if t_high else None,
            "target_source": target_source,
            "analyst_count": g("numberOfAnalystOpinions"),
            "recommendation":g("recommendationKey"),
            "recommendation_mean": g("recommendationMean"),
            "fwd_pe":        round(fwd_pe, 1) if fwd_pe else None,
            "revenue_growth":rg_pct,
            "op_margin":     om_pct,
            "short_pct":     sp_pct,
            "beta":          g("beta"),
            "projections":   projections,
            "optimal_play":  optimal_play,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


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

    # ── HISTORY: reconcile new/off-screener state ──
    history = update_screener_history(main_results)
    today = datetime.now().date().isoformat()
    threshold = (datetime.now().date() - timedelta(days=NEW_TO_SCREENER_DAYS)).isoformat()
    hist_tickers = history.get("tickers", {})

    # New-to-screener: still active, first_seen within window
    new_screener_stocks = []
    for r in main_results:
        info = hist_tickers.get(r["ticker"], {})
        fs = info.get("first_seen")
        if not fs or fs < threshold:
            continue
        fs_price = info.get("first_seen_price")
        pct_since = None
        if fs_price and r.get("price"):
            pct_since = round((r["price"] - fs_price) / fs_price * 100, 1)
        new_screener_stocks.append({
            **r,
            "first_seen": fs,
            "first_seen_price": fs_price,
            "first_seen_trend": info.get("first_seen_trend"),
            "days_on_screener": _days_between(fs, today),
            "pct_since_added": pct_since,
        })
    new_screener_stocks.sort(key=lambda x: x.get("first_seen", ""), reverse=True)

    # Off-screener: inactive in history, fetch live prices for perf tracking
    off_tickers = [t for t, i in hist_tickers.items() if not i.get("active")]
    off_results = []
    if off_tickers:
        off_tasks = [loop.run_in_executor(executor, fetch_price_only, t) for t in off_tickers]
        off_raw = await asyncio.gather(*off_tasks, return_exceptions=True)
        for t, r in zip(off_tickers, off_raw):
            if isinstance(r, Exception) or r is None:
                continue
            info = hist_tickers.get(t, {})
            exit_price = info.get("exit_price")
            first_price = info.get("first_seen_price")
            current_price = r.get("price")
            pct_since_exit = None
            pct_total = None
            if exit_price and current_price:
                pct_since_exit = round((current_price - exit_price) / exit_price * 100, 1)
            if first_price and current_price:
                pct_total = round((current_price - first_price) / first_price * 100, 1)
            off_results.append({
                "ticker": t,
                "name": r.get("name", t),
                "day_pct": r.get("day_pct"),
                "first_seen": info.get("first_seen"),
                "first_seen_price": first_price,
                "first_seen_trend": info.get("first_seen_trend") or info.get("last_trend"),
                "exit_date": info.get("exit_date"),
                "exit_price": exit_price,
                "current_price": current_price,
                "pct_since_exit": pct_since_exit,
                "pct_total": pct_total,
                "days_since_exit": _days_between(info.get("exit_date", today), today) if info.get("exit_date") else 0,
                "days_held": _days_between(info.get("first_seen", today), info.get("exit_date", today)),
            })
    off_results.sort(key=lambda x: (x.get("exit_date") or ""), reverse=True)

    # Aggregate performance signal: does dropping a ticker tend to be right?
    valid_perf = [x["pct_since_exit"] for x in off_results if x.get("pct_since_exit") is not None]
    off_screener_perf = {
        "count": len(off_results),
        "avg_pct_since_exit": round(sum(valid_perf) / len(valid_perf), 1) if valid_perf else None,
        "winners_after_exit": sum(1 for p in valid_perf if p > 0),
        "losers_after_exit": sum(1 for p in valid_perf if p <= 0),
    }

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

    # Persist + build call-volume history with live perf vs. first-seen price
    call_archive = update_call_volume_archive(unusual_call_stocks)
    today_iso_cv = datetime.now().date().isoformat()
    # Build a quick lookup for current prices from the combined universe
    combined_price_lookup = {r["ticker"]: r for r in combined}
    call_history_rows = []
    for t, info in call_archive.get("tickers", {}).items():
        live = combined_price_lookup.get(t, {})
        cur_price = live.get("price")
        cur_day_pct = live.get("day_pct")
        entry_price = info.get("first_seen_price")
        perf_pct = None
        if cur_price and entry_price:
            perf_pct = round((cur_price - entry_price) / entry_price * 100, 2)
        days_tracked = _days_between(info["first_seen"], today_iso_cv) if info.get("first_seen") else 0
        days_since_last = _days_between(info.get("last_seen_unusual", today_iso_cv), today_iso_cv)
        call_history_rows.append({
            "ticker": t,
            "name": info.get("first_seen_name") or live.get("name") or t,
            "trend": info.get("first_seen_trend") or live.get("trend"),
            "first_seen": info.get("first_seen"),
            "first_seen_price": entry_price,
            "last_seen_unusual": info.get("last_seen_unusual"),
            "appearance_count": info.get("appearance_count", 1),
            "days_tracked": days_tracked,
            "days_since_last": days_since_last,
            "current_price": cur_price,
            "day_pct": cur_day_pct,
            "perf_pct": perf_pct,
            "still_active": bool(info.get("active")),
            "last_seen_vol_oi": info.get("last_seen_vol_oi"),
        })
    # Sort: still active first, then by perf desc
    call_history_rows.sort(key=lambda x: (not x.get("still_active"), -(x.get("perf_pct") or -1e9)))

    # Summary
    cv_valid = [r["perf_pct"] for r in call_history_rows if r.get("perf_pct") is not None]
    call_history_summary = {
        "count": len(call_history_rows),
        "avg_perf_pct": round(sum(cv_valid) / len(cv_valid), 2) if cv_valid else None,
        "winners": sum(1 for v in cv_valid if v > 0),
        "losers":  sum(1 for v in cv_valid if v <= 0),
    }

    # Daily perf rollup across the screener universe
    day_vals = [r["day_pct"] for r in main_results if r.get("day_pct") is not None]
    radar_day_vals = [r["day_pct"] for r in radar_results if r.get("day_pct") is not None]
    daily_perf = {
        "screener_avg":  round(sum(day_vals)/len(day_vals), 2) if day_vals else None,
        "screener_up":   sum(1 for p in day_vals if p > 0),
        "screener_down": sum(1 for p in day_vals if p < 0),
        "screener_best": max(main_results, key=lambda r: r.get("day_pct") or -1e9, default={}).get("ticker") if day_vals else None,
        "screener_worst":min(main_results, key=lambda r: r.get("day_pct") or  1e9, default={}).get("ticker") if day_vals else None,
        "screener_best_pct":  round(max(day_vals), 2) if day_vals else None,
        "screener_worst_pct": round(min(day_vals), 2) if day_vals else None,
        "radar_avg":     round(sum(radar_day_vals)/len(radar_day_vals), 2) if radar_day_vals else None,
    }

    # ── Adjacent universe (rotates daily) ──
    adjacent_picks = pick_adjacent_for_today(per_trend=5)
    adjacent_results = []
    if adjacent_picks:
        adj_tasks = [loop.run_in_executor(executor, fetch_adjacent_basic, t, tr) for t, tr in adjacent_picks]
        adj_raw = await asyncio.gather(*adj_tasks, return_exceptions=True)
        for r in adj_raw:
            if isinstance(r, Exception) or r is None:
                continue
            adjacent_results.append(r)
    adjacent_results.sort(key=lambda x: ((x.get("trend") or ""), -(x.get("day_pct") or -999)))

    # ── Daily favorites: adjacent / top picks / fundamentals ──
    today_iso = datetime.now().date().isoformat()
    seed_int = datetime.now().date().toordinal()
    favs = _load_favorites()

    # Adjacent favorites (top 3 by composite score, from today's adjacent rotation)
    if today_iso not in favs.get("adjacent_favorites", {}):
        scored = sorted(
            [(r, _score_adjacent_for_favs(r)) for r in adjacent_results if r.get("price")],
            key=lambda x: x[1], reverse=True
        )[:3]
        favs.setdefault("adjacent_favorites", {})[today_iso] = [{
            "ticker": r["ticker"], "entry_price": r["price"], "entry_date": today_iso,
            "trend": r.get("trend"), "name": r.get("name"), "sector": r.get("sector"),
            "rationale": f"Strong rotation candidate: day {r.get('day_pct')}% · 52W {r.get('wk52_change_pct')}% · rev growth {r.get('revenue_growth')}% · GM {r.get('gross_margin')}%",
        } for r, _ in scored]

    # Today's market-wide top picks — date-seeded shuffle of curated universe
    top_picks_today_full = []
    if today_iso not in favs.get("top_picks", {}):
        rnd_t = random.Random(seed_int + 7)
        top_universe = list(TOP_PICKS_UNIVERSE); rnd_t.shuffle(top_universe)
        chosen = top_universe[:5]
        tp_tasks = [loop.run_in_executor(executor, fetch_market_basic, t, "Top Picks") for t in chosen]
        tp_raw = await asyncio.gather(*tp_tasks, return_exceptions=True)
        top_picks_today_full = [r for r in tp_raw if r and not isinstance(r, Exception) and r.get("price")]
        favs.setdefault("top_picks", {})[today_iso] = [{
            "ticker": r["ticker"], "entry_price": r["price"], "entry_date": today_iso,
            "name": r.get("name"), "sector": r.get("sector"), "industry": r.get("industry"),
            "rationale": _top_pick_rationale(r),
        } for r in top_picks_today_full]

    # Today's fundamental picks — fetch 10 candidates, rank top 5 by composite score
    fundamental_picks_today_full = []
    if today_iso not in favs.get("fundamental_picks", {}):
        rnd_f = random.Random(seed_int + 13)
        f_universe = list(FUNDAMENTAL_UNIVERSE); rnd_f.shuffle(f_universe)
        candidates = f_universe[:10]
        fp_tasks = [loop.run_in_executor(executor, fetch_market_basic, t, "Fundamentals") for t in candidates]
        fp_raw = await asyncio.gather(*fp_tasks, return_exceptions=True)
        fp_full = [r for r in fp_raw if r and not isinstance(r, Exception) and r.get("price")]
        fundamental_picks_today_full = sorted(fp_full, key=_score_fundamental, reverse=True)[:5]
        favs.setdefault("fundamental_picks", {})[today_iso] = [{
            "ticker": r["ticker"], "entry_price": r["price"], "entry_date": today_iso,
            "name": r.get("name"), "sector": r.get("sector"), "industry": r.get("industry"),
            "rationale": _fundamental_rationale(r),
            "fwd_pe": r.get("fwd_pe"), "fcf_yield": r.get("fcf_yield"), "drawdown_pct": r.get("drawdown_pct"),
            "gross_margin": r.get("gross_margin"), "roe": r.get("roe"), "debt_to_equity": r.get("debt_to_equity"),
            "ev_ebitda": r.get("ev_ebitda"), "score": round(_score_fundamental(r), 1),
        } for r in fundamental_picks_today_full]

    _save_favorites(favs)

    # Build price map for portfolios & AI portfolio perf
    price_map = _build_price_map(main_results, radar_results, off_results)
    # Fold adjacent + today's full-fetch picks into the price map
    for r in adjacent_results + top_picks_today_full + fundamental_picks_today_full:
        if r.get("price"):
            price_map[r["ticker"]] = {
                "price": r["price"], "prev_close": r.get("prev_close"),
                "day_pct": r.get("day_pct"), "name": r.get("name"),
                "trend": r.get("trend") or r.get("sector"),
            }
    # Ensure archived favorites have current prices
    all_archived_tickers = set()
    for cat in ("adjacent_favorites", "top_picks", "fundamental_picks"):
        for date_key, picks in favs.get(cat, {}).items():
            for p in picks:
                all_archived_tickers.add(p["ticker"])
    missing = [t for t in all_archived_tickers if t not in price_map]
    if missing:
        m_tasks = [loop.run_in_executor(executor, fetch_price_only, t) for t in missing]
        m_raw = await asyncio.gather(*m_tasks, return_exceptions=True)
        for t, r in zip(missing, m_raw):
            if isinstance(r, Exception) or r is None or not r.get("price"):
                continue
            price_map[t] = {"price": r["price"], "day_pct": r.get("day_pct"),
                            "name": r.get("name"), "prev_close": None}

    def _flatten_favs(category):
        out = []
        for date_key, picks in favs.get(category, {}).items():
            for p in picks:
                info = price_map.get(p["ticker"], {})
                cur = info.get("price")
                ep = p.get("entry_price")
                perf_pct = round((cur - ep) / ep * 100, 2) if (cur and ep) else None
                days_held = _days_between(p["entry_date"], today_iso)
                out.append({**p,
                    "current_price": cur,
                    "day_pct": info.get("day_pct"),
                    "perf_pct": perf_pct,
                    "perf_dollars": round((cur - ep), 2) if (cur and ep) else None,
                    "days_held": days_held,
                })
        out.sort(key=lambda x: x.get("entry_date", ""), reverse=True)
        return out

    adjacent_favorites_history    = _flatten_favs("adjacent_favorites")
    top_picks_history             = _flatten_favs("top_picks")
    fundamental_picks_history     = _flatten_favs("fundamental_picks")

    def _summary(rows):
        valid = [r["perf_pct"] for r in rows if r.get("perf_pct") is not None]
        return {
            "count": len(rows),
            "avg_perf_pct": round(sum(valid)/len(valid), 2) if valid else None,
            "winners": sum(1 for v in valid if v > 0),
            "losers":  sum(1 for v in valid if v <= 0),
        }

    favorites_payload = {
        "adjacent": {"history": adjacent_favorites_history, "today": favs.get("adjacent_favorites", {}).get(today_iso, []),
                     "summary": _summary(adjacent_favorites_history)},
        "top_picks": {"history": top_picks_history, "today": favs.get("top_picks", {}).get(today_iso, []),
                      "summary": _summary(top_picks_history)},
        "fundamentals": {"history": fundamental_picks_history, "today": favs.get("fundamental_picks", {}).get(today_iso, []),
                         "summary": _summary(fundamental_picks_history)},
    }

    ai_portfolio_raw = _load_or_seed_ai_portfolio(price_map)
    ai_portfolio = _compute_portfolio_perf(ai_portfolio_raw, price_map)

    # ── Upswing predictions: score every ticker (main + radar) ──
    upswing_universe = main_results + radar_results
    upswing_rows = []
    for r in upswing_universe:
        u = compute_upswing_score(r)
        if u["upswing_score"] <= 0 and not u["upswing_signals"]:
            continue
        upswing_rows.append({
            "ticker": r["ticker"],
            "name": r.get("name"),
            "trend": r.get("trend"),
            "price": r.get("price"),
            "day_pct": r.get("day_pct"),
            "wk52_change_pct": r.get("wk52_change_pct"),
            "market_cap_b": r.get("market_cap_b"),
            "bear_1y": r.get("bear_1y"), "base_1y": r.get("base_1y"), "bull_1y": r.get("bull_1y"),
            "bear_pct": r.get("bear_pct"), "base_pct": r.get("base_pct"), "bull_pct": r.get("bull_pct"),
            "target_source": r.get("target_source"),
            "short_pct": r.get("short_pct"),
            "vol_oi_ratio": r.get("vol_oi_ratio"),
            "eps_q_growth_pct": r.get("eps_q_growth_pct"),
            "rev_q_growth_pct": r.get("rev_q_growth_pct"),
            "ma50": r.get("ma50"), "ma200": r.get("ma200"),
            "recommendation_key": r.get("recommendation_key"),
            "num_analysts": r.get("num_analysts"),
            **u,
        })
    upswing_rows.sort(key=lambda x: x["upswing_score"], reverse=True)

    # ── Persist + compute history ──
    upswing_archive = update_upswing_archive(upswing_rows)
    today_iso_up = datetime.now().date().isoformat()
    upswing_history_rows = []
    for rec in upswing_archive.get("records", []):
        live = price_map.get(rec["ticker"], {}) if 'price_map' in dir() else {}
        # price_map isn't built yet at this point — use the raw upswing universe instead
        if not live:
            live = next((x for x in upswing_universe if x.get("ticker") == rec["ticker"]), {})

        cur = live.get("price") if live else None
        entry = rec.get("first_seen_price")
        ec_price = rec.get("earnings_close_price")

        perf_pct = round((cur - entry) / entry * 100, 2) if (cur and entry) else None
        perf_post = round((cur - ec_price) / ec_price * 100, 2) if (cur and ec_price) else None
        # Earnings-day reaction: close-on-earnings vs entry price (the move INTO/AROUND earnings)
        earnings_reaction = round((ec_price - entry) / entry * 100, 2) if (ec_price and entry) else None

        days_since_pred = _days_between(rec.get("first_seen", today_iso_up), today_iso_up)
        days_to_e = None
        e_status = None
        if rec.get("earnings_date"):
            try:
                ed_date = datetime.fromisoformat(rec["earnings_date"]).date()
                days_to_e = (ed_date - datetime.now().date()).days
                e_status = f"In {days_to_e}d" if days_to_e > 0 else ("Today" if days_to_e == 0 else f"{-days_to_e}d ago")
            except Exception:
                pass

        upswing_history_rows.append({
            **rec,
            "current_price": cur,
            "day_pct": live.get("day_pct") if live else None,
            "perf_pct": perf_pct,
            "perf_post_earnings": perf_post,
            "earnings_reaction_pct": earnings_reaction,
            "days_since_prediction": days_since_pred,
            "days_to_earnings": days_to_e,
            "earnings_status_label": e_status,
        })

    # Sort: resolved + biggest absolute moves first, then active by current perf
    def _hist_key(r):
        is_resolved = r.get("status") == "resolved"
        primary = r.get("perf_post_earnings") if is_resolved else r.get("perf_pct")
        return (not is_resolved, -(primary if primary is not None else -1e9))
    upswing_history_rows.sort(key=_hist_key)

    # Summary
    resolved = [r for r in upswing_history_rows if r.get("status") == "resolved" and r.get("perf_post_earnings") is not None]
    upswing_history_summary = {
        "total":   len(upswing_history_rows),
        "active":  sum(1 for r in upswing_history_rows if r.get("status") == "active"),
        "resolved": len(resolved),
        "avg_post_earnings_pct": round(sum(r["perf_post_earnings"] for r in resolved) / len(resolved), 2) if resolved else None,
        "post_winners": sum(1 for r in resolved if r["perf_post_earnings"] > 0),
        "post_losers":  sum(1 for r in resolved if r["perf_post_earnings"] <= 0),
        "avg_earnings_reaction_pct": round(sum(r["earnings_reaction_pct"] for r in upswing_history_rows if r.get("earnings_reaction_pct") is not None) / max(1, sum(1 for r in upswing_history_rows if r.get("earnings_reaction_pct") is not None)), 2) if any(r.get("earnings_reaction_pct") is not None for r in upswing_history_rows) else None,
    }

    payload = {
        "timestamp": datetime.now().isoformat(),
        "upswing_predictions": upswing_rows,
        "upswing_history": upswing_history_rows,
        "upswing_history_summary": upswing_history_summary,
        "daily_perf": daily_perf,
        "price_map": price_map,
        "ai_portfolio": ai_portfolio,
        "adjacent_stocks": adjacent_results,
        "adjacent_refresh_date": datetime.now().date().isoformat(),
        "favorites": favorites_payload,
        "stocks": main_results,
        "radar_stocks": radar_results,
        "backlog_stocks": backlog_stocks,
        "unusual_call_stocks": unusual_call_stocks,
        "call_history": call_history_rows,
        "call_history_summary": call_history_summary,
        "new_screener_stocks": new_screener_stocks,
        "off_screener_stocks": off_results,
        "off_screener_perf": off_screener_perf,
        "trends": trend_summaries,
        "total_screened": len(main_tickers),
        "total_returned": len(main_results),
        "errors": errors,
    }
    global _LAST_SCREEN
    _LAST_SCREEN = payload
    return JSONResponse(payload)


if __name__ == "__main__":
    import os
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")), log_level="info")
