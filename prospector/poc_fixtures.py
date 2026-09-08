"""
POC-only signal fixtures
────────────────────────
Real, dated why-now signals gathered live via Exa earlier this session, frozen
here so the POC produces genuine dossiers before the user wires their own Exa
key. In production `signals.ExaSignalProvider` fetches these live; this module
just lets the qualifier be proven end-to-end today. Not shipped — a demo aid.
"""
from __future__ import annotations

from .models import Lead, Signal
from .signals import SignalProvider

# company-name substring (lowercase) → the signals we found for it
_FIXTURES: dict[str, list[Signal]] = {
    "maruti": [
        Signal("Maruti Suzuki inaugurates Kharkhoda 'Suzuki Smart Factory'",
               "₹35,000 cr facility built on the Suzuki Smart Factory concept and Industry 5.0 — "
               "human-aware collaborative robots (COBOTS), real-time operational visualization, "
               "100% renewable energy.",
               "https://www.marutisuzuki.com/corporate/media/press-releases/2026/july",
               "2026-07", "marutisuzuki.com"),
        Signal("Maruti Suzuki Hansalpur Plant D begins commercial production",
               "Fourth plant at Hansalpur (Gujarat) takes the site to 1 million units/yr; "
               "₹3,900 cr Plant D, initially producing the e VITARA BEV.",
               "https://www.marutisuzuki.com/corporate/media/press-releases/2026/july",
               "2026-07", "marutisuzuki.com"),
    ],
    "arcelormittal": [
        Signal("AM/NS India breaks ground on ₹70,000 cr greenfield integrated steel plant, Andhra Pradesh",
               "8.2 mtpa phase-1 capacity on 2,200 acres near Visakhapatnam; a host of downstream lines "
               "come up alongside upstream capacity; first units operational by end-2028 / early-2029.",
               "https://economictimes.indiatimes.com/industry/indl-goods/svs/steel",
               "2026-03", "economictimes.indiatimes.com"),
        Signal("AM/NS India inaugurates new Pickling Line & Tandem Cold Mill at Hazira",
               "2 MT advanced high-strength steel (AHSS) line for the automotive industry, part of the "
               "₹60,000 cr Hazira expansion (capacity 9 → 15 MT).",
               "https://www.outlookbusiness.com/corporate/amns-india-inaugurates-production-line-at-hazira",
               "2026-04", "outlookbusiness.com"),
    ],
    "sun": [   # sheet company is "Sunpharma"
        Signal("Sun Pharma harmonising sterile & non-sterile formulation plants across India",
               "Deploying unified electronic Batch Records (eBR) and automated digital eLogbooks; "
               "ensuring MES and local control hardware talk to central dashboards to prevent "
               "data-integrity gaps before international audits.",
               "https://indiaautomationhub.com/ai-meets-gmp-how-process-automation-is-reshaping-pharma-manufacturing-in-india",
               "2026-06", "indiaautomationhub.com"),
        Signal("Sun Pharma hiring: Manager – IT / IIoT (Pharma), Halol plant",
               "Live posting (Aug 2026) seeking proven Industry 4.0 / IIoT / smart-manufacturing "
               "experience — MES, SCADA, PLC/DCS, Historian, SAP integration, 21 CFR Part 11.",
               "https://careers.sunpharma.com/job/Halol-Manager-IT-IIoT-Pharma",
               "2026-08", "careers.sunpharma.com"),
    ],
}


class FixtureSignalProvider(SignalProvider):
    name = "fixtures (frozen Exa results — POC demo)"

    def fetch(self, lead: Lead, focus: str = "") -> list[Signal]:
        c = (lead.company or "").lower()
        for key, sigs in _FIXTURES.items():
            if key in c:
                return sigs
        return []
