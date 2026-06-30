from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class CareerPageConfig:
    company: str
    career_url: str
    portal_type: str  # lever, greenhouse, workday, rippling, custom
    regional_url: Optional[str] = None  
    ats_slug: Optional[str] = None  
    job_link_patterns: List[str] = field(default_factory=list)
    navigation_steps: List[dict] = field(default_factory=list)
    model_instructions: str = ""
    pagination_selector: Optional[str] = None
    max_pages: int = 20

# ---------------------------------------------------------------------------
# Navigation instructions teach the scraper (and LLM) how each portal works.
# ---------------------------------------------------------------------------

CAREER_PAGE_REGISTRY: Dict[str, CareerPageConfig] = {
    # --- BIG TECH ---
    "uber": CareerPageConfig(
        company="Uber",
        career_url="https://www.uber.com/global/en/careers/list/",
        regional_url="https://www.uber.com/global/en/careers/list/",
        portal_type="custom_uber",
        job_link_patterns=[
            r"uber\.com/[^/]+/careers/list/\d+",
            r"greenhouse\.io/uber[^/]*/jobs/\d+"
        ],
        navigation_steps=[
            {"action": "goto", "url": "{regional_url}"},
            {"action": "wait", "ms": 4000},
            {"action": "scroll", "times": 6, "pause_ms": 1000},
            {"action": "click_if_visible", "selector": "button[data-tracking='load-more'], button:has-text('Load more')", "max_clicks": 5},
        ],
        model_instructions="Extract job cards mapping directly to /careers/list/ID."
    ),
    "google": CareerPageConfig(
        company="Google",
        career_url="https://www.google.com/about/careers/applications/jobs/results",
        regional_url="https://www.google.com/about/careers/applications/jobs/results",
        portal_type="google_careers",
        job_link_patterns=[
            r"jobs/results/\d+",
            r"careers\.google\.com/jobs/results/\d+"
        ],
        navigation_steps=[
            {"action": "goto", "url": "{regional_url}"},
            {"action": "wait", "ms": 4000},
            {"action": "scroll", "times": 5, "pause_ms": 800},
        ],
        model_instructions="Target locations matching the desired region."
    ),
    "microsoft": CareerPageConfig(
        company="Microsoft",
        career_url="https://careers.microsoft.com/us/en/search-results",
        regional_url="https://careers.microsoft.com/us/en/search-results",
        portal_type="phenom",
        job_link_patterns=[
            r"careers\.microsoft\.com/us/en/job/\d+"
        ],
        navigation_steps=[
            {"action": "goto", "url": "{regional_url}"},
            {"action": "wait", "ms": 4000},
            {"action": "scroll", "times": 5, "pause_ms": 800},
        ],
        model_instructions="Identify software engineering and applied science roles."
    ),

    # --- QUANT / HFT / FINANCE ---
    "d. e. shaw": CareerPageConfig(
        company="D. E. Shaw",
        career_url="https://www.deshaw.com/careers",
        regional_url="https://www.deshaw.com/careers",
        portal_type="custom_deshaw",
        job_link_patterns=[
            r"deshawindia\.com/careers/[^?\s]+",
            r"deshaw\.com/careers/[^?\s]+"
        ],
        navigation_steps=[
            {"action": "goto", "url": "{regional_url}"},
            {"action": "wait", "ms": 4000},
            {"action": "scroll", "times": 4, "pause_ms": 800},
        ],
        model_instructions="Focus purely on systems engineering, quantitative strategies, and financial research clusters."
    ),
    "tower research capital": CareerPageConfig(
        company="Tower Research Capital",
        career_url="https://boards.greenhouse.io/towerresearchcapital",
        regional_url="https://boards.greenhouse.io/towerresearchcapital",
        portal_type="greenhouse",
        job_link_patterns=[
            r"greenhouse\.io/towerresearchcapital/jobs/\d+"
        ],
        navigation_steps=[
            {"action": "goto", "url": "{regional_url}"},
            {"action": "wait", "ms": 3000}
        ],
        model_instructions="Target locations matching the target region or Remote."
    ),
    "qrt": CareerPageConfig(
        company="QRT",
        career_url="https://www.qrt.com/careers/",
        regional_url="https://quadrature.com/jobs/",
        portal_type="workable",
        job_link_patterns=[
            r"quadrature\.com/jobs/[^?\s]+",
            r"apply\.workable\.com/quadrature"
        ],
        navigation_steps=[
            {"action": "goto", "url": "{regional_url}"},
            {"action": "wait", "ms": 3500},
            {"action": "scroll", "times": 4, "pause_ms": 700}
        ],
        model_instructions="Identify global alpha research and quantitative execution engineering."
    ),
    "aqr capital management": CareerPageConfig(
        company="AQR Capital Management",
        career_url="https://careers.aqr.com/jobs",
        regional_url="https://careers.aqr.com/jobs",
        portal_type="custom_aqr",
        job_link_patterns=[
            r"careers\.aqr\.com/jobs/\d+"
        ],
        navigation_steps=[
            {"action": "goto", "url": "{regional_url}"},
            {"action": "wait", "ms": 4000},
            {"action": "scroll", "times": 3, "pause_ms": 800}
        ],
        model_instructions="Focus on engineering and quantitative analysis roles."
    ),
    "imc trading": CareerPageConfig(
        company="IMC Trading",
        career_url="https://www.imc.com/eu/careers/",
        regional_url="https://www.imc.com/eu/careers/jobs",
        portal_type="custom_imc",
        job_link_patterns=[
            r"imc\.com/[^/]+/careers/jobs/[^?\s]+"
        ],
        navigation_steps=[
            {"action": "goto", "url": "{regional_url}"},
            {"action": "wait", "ms": 4000},
            {"action": "scroll", "times": 3, "pause_ms": 600}
        ],
        model_instructions="Extract explicitly filtered engineering and quant roles."
    ),

    # --- INVESTMENT BANKS ---
    "goldman sachs": CareerPageConfig(
        company="Goldman Sachs",
        career_url="https://higher.gs.com/",
        regional_url="https://higher.gs.com/roles",
        portal_type="custom_gs",
        job_link_patterns=[
            r"higher\.gs\.com/roles/\d+"
        ],
        navigation_steps=[
            {"action": "goto", "url": "{regional_url}"},
            {"action": "wait", "ms": 6000},
            {"action": "scroll", "times": 5, "pause_ms": 1000}
        ],
        model_instructions="Target quantitative, data science, and core engineering roles."
    ),
    "j p morgan": CareerPageConfig(
        company="J P Morgan",
        career_url="https://careers.jpmorgan.com/us/en/search-results",
        regional_url="https://careers.jpmorgan.com/us/en/search-results",
        portal_type="custom_jpm",
        job_link_patterns=[
            r"careers\.jpmorgan\.com/[^/]+/[^/]+/careers/job/\d+"
        ],
        navigation_steps=[
            {"action": "goto", "url": "{regional_url}"},
            {"action": "wait", "ms": 5000},
            {"action": "scroll", "times": 4, "pause_ms": 800}
        ],
        model_instructions="Filter for quantitative research, AI, and software engineering roles."
    ),
    "morgan stanley": CareerPageConfig(
        company="Morgan Stanley",
        career_url="https://morganstanley.eightfold.ai/careers",
        regional_url="https://morganstanley.eightfold.ai/careers",
        portal_type="eightfold",
        job_link_patterns=[
            r"/careers/job/\d+"
        ],
        navigation_steps=[
            {"action": "goto", "url": "{regional_url}"},
            {"action": "wait", "ms": 5000},
            {"action": "scroll", "times": 4, "pause_ms": 600}
        ],
        model_instructions="Capture roles relevant to the user's targeted location."
    ),

    # --- SEMICONDUCTORS & HARDWARE ---
    "nvidia": CareerPageConfig(
        company="Nvidia",
        career_url="https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite",
        regional_url="https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite",
        portal_type="workday",
        job_link_patterns=[
            r"nvidia\.wd5\.myworkdayjobs\.com/[^/]+/job/[^/]+/[^/]+_JR\d+"
        ],
        navigation_steps=[
            {"action": "goto", "url": "{regional_url}"},
            {"action": "wait", "ms": 5000},
            {"action": "scroll", "times": 4, "pause_ms": 800}
        ],
        model_instructions="Identify deep learning, applied math, and systems software roles."
    ),
    "amd": CareerPageConfig(
        company="AMD",
        career_url="https://careers.amd.com/careers-home/jobs",
        regional_url="https://careers.amd.com/careers-home/jobs",
        portal_type="successfactors",
        job_link_patterns=[
            r"careers\.amd\.com/careers-home/jobs/\d+"
        ],
        navigation_steps=[
            {"action": "goto", "url": "{regional_url}"},
            {"action": "wait", "ms": 4000},
            {"action": "scroll", "times": 3, "pause_ms": 800}
        ],
        model_instructions="Focus on ML optimization, hardware engineering, and systems software."
    ),

    # --- UNICORNS & OTHER TECH ---
    "meesho": CareerPageConfig(
        company="Meesho",
        career_url="https://jobs.lever.co/meesho",
        regional_url="https://jobs.lever.co/meesho",
        portal_type="lever",
        job_link_patterns=[
            r"lever\.co/meesho/[a-f0-9-]+"
        ],
        navigation_steps=[
            {"action": "goto", "url": "{regional_url}"},
            {"action": "wait", "ms": 3000}
        ],
        model_instructions="Target Data Science, Analyst, and Applied Research."
    ),
    "rippling": CareerPageConfig(
        company="Rippling",
        career_url="https://ats.rippling.com/rippling/jobs",
        regional_url="https://ats.rippling.com/rippling/jobs",
        portal_type="custom_rippling",
        job_link_patterns=[
            r"ats\.rippling\.com/rippling/jobs/[a-f0-9-]+"
        ],
        navigation_steps=[
            {"action": "goto", "url": "{regional_url}"},
            {"action": "wait", "ms": 3000},
            {"action": "scroll", "times": 3, "pause_ms": 500}
        ],
        model_instructions="Focus purely on engineering and data roles."
    ),
    "bcg x": CareerPageConfig(
        company="BCG X",
        career_url="https://careers.bcg.com/x",
        regional_url="https://careers.bcg.com/global/en/search-results",
        portal_type="custom_bcg",
        job_link_patterns=[
            r"careers\.bcg\.com/[^/]+/[^/]+/job/\d+"
        ],
        navigation_steps=[
            {"action": "goto", "url": "{regional_url}"},
            {"action": "wait", "ms": 5000},
            {"action": "scroll", "times": 4, "pause_ms": 800}
        ],
        model_instructions="Capture openings matching advanced analytics and data science research."
    ),
    "ebay": CareerPageConfig(
        company="eBay",
        career_url="https://jobs.ebayinc.com/us/en",
        regional_url="https://jobs.ebayinc.com/us/en/search-results",
        portal_type="phenom",
        job_link_patterns=[
            r"jobs\.ebayinc\.com/(?:[^/]+/)?job/\d+"
        ],
        navigation_steps=[
            {"action": "goto", "url": "{regional_url}"},
            {"action": "wait", "ms": 4500},
            {"action": "scroll", "times": 4, "pause_ms": 600}
        ],
        model_instructions="Extract explicitly filtered engineering, machine learning science, and analytics."
    )
}

# ---------------------------------------------------------------------------
# Required Helper Functions for job_agent.py
# ---------------------------------------------------------------------------

def normalize_company_key(name: str) -> str:
    return name.strip().lower()

def get_career_config(company: str) -> Optional[CareerPageConfig]:
    key = normalize_company_key(company)
    if key in CAREER_PAGE_REGISTRY:
        return CAREER_PAGE_REGISTRY[key]
    for registry_key, cfg in CAREER_PAGE_REGISTRY.items():
        if registry_key in key or key in registry_key:
            return cfg
        if normalize_company_key(cfg.company) == key:
            return cfg
    return None

def get_career_url_map() -> Dict[str, str]:
    """Flat dict for config.json company_career_pages (display name -> URL)."""
    result = {}
    for cfg in CAREER_PAGE_REGISTRY.values():
        url = cfg.regional_url or cfg.career_url
        result[cfg.company] = url
    return result

def get_all_navigation_instructions() -> str:
    """Combined navigation guide injected into LLM prompts."""
    sections = ["# Company Career Portal Navigation Guide\n"]
    for cfg in CAREER_PAGE_REGISTRY.values():
        sections.append(f"## {cfg.company}\nURL: {cfg.regional_url or cfg.career_url}\n{cfg.model_instructions.strip()}\n")
    return "\n".join(sections)

def resolve_start_url(cfg: CareerPageConfig) -> str:
    return cfg.regional_url or cfg.career_url