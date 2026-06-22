"""
Hardcoded career portal URLs and navigation instructions for target companies.
The agent uses these instead of guessing career links via web search.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class CareerPageConfig:
    company: str
    career_url: str
    portal_type: str  # lever, greenhouse, workday, rippling, custom
    india_url: Optional[str] = None  # pre-filtered India listing when available
    ats_slug: Optional[str] = None  # lever/greenhouse/rippling board slug
    job_link_patterns: List[str] = field(default_factory=list)
    navigation_steps: List[dict] = field(default_factory=list)
    model_instructions: str = ""
    pagination_selector: Optional[str] = None
    max_pages: int = 20


# ---------------------------------------------------------------------------
# Navigation instructions teach the scraper (and LLM) how each portal works.
# ---------------------------------------------------------------------------

CAREER_PAGE_REGISTRY: Dict[str, CareerPageConfig] = {
    "uber": CareerPageConfig(
        company="Uber",
        career_url="https://www.uber.com/global/en/careers/list/",
        india_url="https://www.uber.com/global/en/careers/list/?location=IND-",
        portal_type="custom_uber",
        job_link_patterns=[
            r"https?://(?:www\.)?uber\.com/[^/]+/en/careers/list/\d+",
            r"https?://job-boards\.greenhouse\.io/uber[^/]*/jobs/\d+",
        ],
        navigation_steps=[
            {"action": "goto", "url": "{india_url}"},
            {"action": "wait", "ms": 3000},
            {"action": "scroll", "times": 5, "pause_ms": 800},
            {"action": "click_if_visible", "selector": "button:has-text('Load more'), button:has-text('Show more')", "max_clicks": 3},
        ],
        model_instructions="""
UBER CAREERS PORTAL:
1. Start at the India-filtered listing: uber.com/global/en/careers/list/?location=IND-
2. Job cards link to /careers/list/{numeric_id}/ — each is a single job posting.
3. Scroll down to load more roles; click "Load more" if present.
4. Filter mentally for: data scientist, applied scientist, quant, ML, research, analytics.
5. Locations of interest: Bengaluru, Hyderabad, Gurugram, Remote India.
6. Uber Freight roles may appear on boards.greenhouse.io/uberfreight — include those if India-based.
7. Ignore marketing pages, team overviews, and location landing pages without job IDs.
""",
    ),
    "google": CareerPageConfig(
        company="Google",
        career_url="https://www.google.com/about/careers/applications/jobs/results",
        india_url="https://www.google.com/about/careers/applications/jobs/results?location=India",
        portal_type="google_careers",
        job_link_patterns=[
            r"https?://(?:www\.)?google\.com/about/careers/applications/jobs/results/\d+[^?\s]*",
            r"https?://careers\.google\.com/jobs/results/\d+[^?\s]*",
        ],
        navigation_steps=[
            {"action": "goto", "url": "{india_url}"},
            {"action": "wait", "ms": 4000},
            {"action": "fill_if_visible", "selector": "input[aria-label*='Search'], input[type='search']", "text": "{keyword}"},
            {"action": "press", "key": "Enter"},
            {"action": "wait", "ms": 3000},
            {"action": "scroll", "times": 4, "pause_ms": 600},
        ],
        model_instructions="""
GOOGLE CAREERS PORTAL:
1. Use the India location filter: careers applications/jobs/results?location=India
2. Search box accepts role keywords (data scientist, research scientist, quant).
3. Each result links to /jobs/results/{id}-{slug} — open these for full JD.
4. Look for Bengaluru, Hyderabad, Gurgaon/Gurugram, Mumbai, Remote India.
5. Skip "Early Career" internships unless they match seniority in resume.
""",
    ),
    "microsoft": CareerPageConfig(
        company="Microsoft",
        career_url="https://careers.microsoft.com/us/en/search-results",
        india_url="https://careers.microsoft.com/us/en/search-results?keywords=&location=India",
        portal_type="microsoft_careers",
        job_link_patterns=[
            r"https?://careers\.microsoft\.com/[^/]+/[^/]+/job/\d+",
        ],
        navigation_steps=[
            {"action": "goto", "url": "{india_url}"},
            {"action": "wait", "ms": 4000},
            {"action": "fill_if_visible", "selector": "input#search-box, input[name='keywords']", "text": "{keyword}"},
            {"action": "click_if_visible", "selector": "button[type='submit'], button:has-text('Search')"},
            {"action": "wait", "ms": 3000},
            {"action": "scroll", "times": 4, "pause_ms": 600},
        ],
        model_instructions="""
MICROSOFT CAREERS PORTAL:
1. Pre-filter by location=India in search-results URL.
2. Use keywords field for: data scientist, applied scientist, research, quant.
3. Job detail URLs contain /job/{numeric_id}.
4. Target cities: Bengaluru, Hyderabad, Noida, Mumbai. Include remote-friendly roles.
""",
    ),
    "jane street": CareerPageConfig(
        company="Jane Street",
        career_url="https://www.janestreet.com/join-jane-street/open-roles/",
        portal_type="custom_janestreet",
        job_link_patterns=[
            r"https?://www\.janestreet\.com/join-jane-street/[^/\s]+/?$",
            r"https?://www\.janestreet\.com/join-jane-street/[^/]+/[^/\s]+",
        ],
        navigation_steps=[
            {"action": "goto", "url": "{career_url}"},
            {"action": "wait", "ms": 3000},
            {"action": "click_if_visible", "selector": "a:has-text('Experienced'), a:has-text('View open roles')"},
            {"action": "wait", "ms": 2000},
            {"action": "scroll", "times": 5, "pause_ms": 700},
        ],
        model_instructions="""
JANE STREET CAREERS:
1. Entry: janestreet.com/join-jane-street/open-roles/
2. Choose "Experienced Candidates" path for mid/senior roles.
3. Roles are listed as text links (Power Analyst, ML Researcher, Software Engineer, etc.).
4. India/Bengaluru roles exist but many listings are global — check location in JD.
5. User dislikes stale "Options Trader" posts — verify role is currently open.
6. Legitimate recruiter emails end in @janestreet.com only.
""",
    ),
    "d. e. shaw": CareerPageConfig(
        company="D. E. Shaw",
        career_url="https://www.deshaw.com/careers",
        india_url="https://www.deshawindia.com/careers/",
        portal_type="custom_deshaw",
        job_link_patterns=[
            r"https?://www\.deshaw\.com/careers/[^?\s]+",
            r"https?://www\.deshawindia\.com/[^?\s]+",
        ],
        navigation_steps=[
            {"action": "goto", "url": "{india_url}"},
            {"action": "wait", "ms": 3000},
            {"action": "scroll", "times": 5, "pause_ms": 600},
        ],
        model_instructions="""
D. E. SHAW CAREERS:
1. India portal: deshawindia.com/careers/ lists all openings directly.
2. Departments of interest: Quantitative Strategies, Technology, Software Development, Financial Research.
3. Capture job titles like Analyst, Senior Analyst, Associate, etc.
""",
    ),
    "millennium management": CareerPageConfig(
        company="Millennium Management",
        career_url="https://career.mlp.com/careers",
        portal_type="workday",
        job_link_patterns=[
            r"https?://[^/]*mlp[^/]*\.wd\d+\.myworkdayjobs\.com/[^?\s]+",
            r"https?://career\.mlp\.com/[^?\s]+",
        ],
        navigation_steps=[
            {"action": "goto", "url": "{career_url}"},
            {"action": "wait", "ms": 4000},
            {"action": "fill_if_visible", "selector": "input[data-automation-id='keywordSearchInput'], input[placeholder*='Search']", "text": "{keyword}"},
            {"action": "fill_if_visible", "selector": "input[data-automation-id='locationSearchInput']", "text": "Bangalore"},
            {"action": "click_if_visible", "selector": "button[data-automation-id='searchButton']"},
            {"action": "wait", "ms": 3000},
            {"action": "scroll", "times": 4, "pause_ms": 600},
        ],
        model_instructions="""
MILLENNIUM MANAGEMENT (Workday):
1. Portal: career.mlp.com/careers (Workday ATS).
2. Search by keyword + location (Bangalore, Mumbai, London, New York).
3. User dislikes trading-firm culture here — still surface quant/data/research roles for review.
4. Job links contain myworkdayjobs.com or career.mlp.com paths.
""",
    ),
    "tower research capital": CareerPageConfig(
        company="Tower Research Capital",
        career_url="https://www.tower-research.com/open-positions/",
        portal_type="custom",
        job_link_patterns=[
            r"https?://www\.tower-research\.com/open-positions/[^?\s]*",
        ],
        navigation_steps=[
            {"action": "goto", "url": "{career_url}"},
            {"action": "wait", "ms": 3000},
            {"action": "scroll", "times": 4, "pause_ms": 600},
        ],
        model_instructions="""
TOWER RESEARCH CAPITAL:
1. All open roles listed at tower-research.com/open-positions/
2. Look for: Quantitative Researcher, Software Engineer, Trading, ML roles.
3. India presence is limited — verify location before scoring highly.
""",
    ),
    "aqr capital management": CareerPageConfig(
        company="AQR Capital Management",
        career_url="https://careers.aqr.com/jobs",
        portal_type="custom",
        job_link_patterns=[
            r"https?://careers\.aqr\.com/jobs/\d+[^?\s]*",
        ],
        navigation_steps=[
            {"action": "goto", "url": "{career_url}"},
            {"action": "wait", "ms": 3000},
            {"action": "scroll", "times": 4, "pause_ms": 600},
        ],
        model_instructions="""
AQR CAPITAL MANAGEMENT:
1. Job board: careers.aqr.com/jobs
2. Filter for Research, Portfolio Analytics, Technology, Data Science roles.
3. Mostly US/UK based — flag India/remote-friendly roles explicitly.
""",
    ),
    "j p morgan": CareerPageConfig(
        company="J P Morgan",
        career_url="https://careers.jpmorgan.com/us/en/search-results",
        india_url="https://careers.jpmorgan.com/us/en/search-results?country=India",
        portal_type="jpmorgan",
        job_link_patterns=[
            r"https?://careers\.jpmorgan\.com/[^/]+/[^/]+/job/\d+",
        ],
        navigation_steps=[
            {"action": "goto", "url": "{india_url}"},
            {"action": "wait", "ms": 4000},
            {"action": "fill_if_visible", "selector": "input#search", "text": "{keyword}"},
            {"action": "click_if_visible", "selector": "button.search-button, button:has-text('Search')"},
            {"action": "wait", "ms": 3000},
            {"action": "scroll", "times": 4, "pause_ms": 600},
        ],
        model_instructions="""
JP MORGAN CAREERS:
1. Use country=India filter on careers.jpmorgan.com search-results.
2. Search keywords: data scientist, quant researcher, applied AI, strats.
3. Quant Research / Strats roles in Mumbai/Bengaluru are top targets.
""",
    ),
    "goldman sachs": CareerPageConfig(
        company="Goldman Sachs",
        career_url="https://higher.gs.com/",
        portal_type="custom",
        job_link_patterns=[
            r"/roles/\d+",
        ],
        navigation_steps=[
            {"action": "goto", "url": "{career_url}"},
            {"action": "wait", "ms": 4000},
            {"action": "auto_search", "location": "Bengaluru"},
            {"action": "wait", "ms": 4000},
            {"action": "scroll", "times": 4, "pause_ms": 600},
        ],
        pagination_selector="[aria-label='Goto next page'], .gs-pagination__nav-next, button:has-text('Next')",
        max_pages=20,
        model_instructions="""
GOLDMAN SACHS (Experienced Careers):
1. Portal: higher.gs.com
2. Performs keyword search and filters by location 'Bengaluru' by appending 'Bengaluru' to search keywords.
3. Filter/scan for India locations: Bengaluru, Mumbai, Hyderabad.
4. Support pagination through next page selector.
""",
    ),
    "morgan stanley": CareerPageConfig(
        company="Morgan Stanley",
        career_url="https://morganstanley.eightfold.ai/careers",
        portal_type="custom",
        job_link_patterns=[
            r"/careers/job/\d+",
            r"https?://morganstanley\.eightfold\.ai/careers\?pid=\d+[^?\s]*",
        ],
        navigation_steps=[
            {"action": "goto", "url": "{career_url}"},
            {"action": "wait", "ms": 4000},
            {"action": "auto_search", "location": "India"},
            {"action": "wait", "ms": 3000},
            {"action": "scroll", "times": 4, "pause_ms": 600},
        ],
        model_instructions="""
MORGAN STANLEY (Eightfold):
1. Portal: morganstanley.eightfold.ai/careers
2. Search by keyword and location. Fills location with 'India', selects from autocomplete, and searches.
3. Target roles in Bengaluru/Mumbai: data scientist, software engineer, quant developer.
""",
    ),
    "amd": CareerPageConfig(
        company="AMD",
        career_url="https://careers.amd.com/careers-home/jobs",
        india_url="https://careers.amd.com/careers-home/jobs?location=India",
        portal_type="amd_careers",
        job_link_patterns=[
            r"https?://careers\.amd\.com/[^?\s]+/job/\d+",
        ],
        navigation_steps=[
            {"action": "goto", "url": "{india_url}"},
            {"action": "wait", "ms": 4000},
            {"action": "fill_if_visible", "selector": "input[placeholder*='Search'], input[type='search']", "text": "{keyword}"},
            {"action": "wait", "ms": 2000},
            {"action": "scroll", "times": 4, "pause_ms": 600},
        ],
        model_instructions="""
AMD CAREERS:
1. India filter: careers.amd.com/careers-home/jobs?location=India
2. Target: ML engineer, data scientist, research, software roles in Bengaluru/Hyderabad.
""",
    ),
    "nvidia": CareerPageConfig(
        company="Nvidia",
        career_url="https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite",
        india_url="https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite?locations=India",
        portal_type="workday",
        job_link_patterns=[
            r"https?://nvidia\.wd5\.myworkdayjobs\.com/[^?\s]+/job/[^?\s]+",
            r"https?://jobs\.nvidia\.com/careers/job/[^?\s]+",
        ],
        navigation_steps=[
            {"action": "goto", "url": "{india_url}"},
            {"action": "wait", "ms": 4000},
            {"action": "fill_if_visible", "selector": "input[data-automation-id='keywordSearchInput']", "text": "{keyword}"},
            {"action": "click_if_visible", "selector": "button[data-automation-id='searchButton']"},
            {"action": "wait", "ms": 3000},
            {"action": "scroll", "times": 4, "pause_ms": 600},
        ],
        model_instructions="""
NVIDIA (Workday):
1. India listings: nvidia.wd5.myworkdayjobs.com with locations=India filter.
2. Also mirrors on jobs.nvidia.com — both are valid job URLs.
3. Focus: ML/DL engineer, research scientist, data scientist, systems roles in Bengaluru/Pune/Hyderabad.
""",
    ),
    "meesho": CareerPageConfig(
        company="Meesho",
        career_url="https://jobs.lever.co/meesho",
        portal_type="lever",
        ats_slug="meesho",
        job_link_patterns=[
            r"https?://jobs\.lever\.co/meesho/[a-f0-9-]+",
        ],
        navigation_steps=[
            {"action": "goto", "url": "{career_url}"},
            {"action": "wait", "ms": 2000},
            {"action": "scroll", "times": 3, "pause_ms": 500},
        ],
        model_instructions="""
MEESHO (Lever ATS):
1. All jobs at jobs.lever.co/meesho — single page listing.
2. Lever job URLs: jobs.lever.co/meesho/{uuid}
3. Target: Data Scientist III, Principal Data Scientist, Applied Scientist, ML, Quant-adjacent analytics.
4. All roles are India/Bangalore based — good fit for candidate location preference.
""",
    ),
    "rippling": CareerPageConfig(
        company="Rippling",
        career_url="https://ats.rippling.com/rippling/jobs",
        portal_type="rippling",
        ats_slug="rippling",
        job_link_patterns=[
            r"https?://ats\.rippling\.com/rippling/jobs/[a-f0-9-]+",
        ],
        navigation_steps=[
            {"action": "goto", "url": "{career_url}"},
            {"action": "wait", "ms": 3000},
            {"action": "scroll", "times": 3, "pause_ms": 500},
        ],
        model_instructions="""
RIPPLING (Rippling ATS):
1. Board: ats.rippling.com/rippling/jobs
2. Job URLs: ats.rippling.com/rippling/jobs/{uuid}
3. Filter for data, ML, product analytics, engineering roles with India/remote availability.
""",
    ),
    "qrt": CareerPageConfig(
        company="QRT",
        career_url="https://www.qrt.com/careers/",
        portal_type="custom",
        job_link_patterns=[
            r"https?://www\.qrt\.com/careers/[^?\s]+",
        ],
        navigation_steps=[
            {"action": "goto", "url": "{career_url}"},
            {"action": "wait", "ms": 3000},
            {"action": "scroll", "times": 3, "pause_ms": 600},
        ],
        model_instructions="""
QRT (Quadrature / quant fund):
1. Careers hub: qrt.com/careers/
2. Look for quantitative researcher, developer, data science roles.
3. Primarily Europe/Asia hubs — verify India or remote eligibility.
""",
    ),
    "bcg x": CareerPageConfig(
        company="BCG X",
        career_url="https://careers.bcg.com/global/en/search-results",
        india_url="https://careers.bcg.com/global/en/search-results?location=India",
        portal_type="bcg",
        job_link_patterns=[
            r"https?://careers\.bcg\.com/[^/]+/[^/]+/job/\d+",
        ],
        navigation_steps=[
            {"action": "goto", "url": "{india_url}"},
            {"action": "wait", "ms": 4000},
            {"action": "fill_if_visible", "selector": "input#keyword-search, input[name='keyword']", "text": "{keyword}"},
            {"action": "click_if_visible", "selector": "button:has-text('Search')"},
            {"action": "wait", "ms": 3000},
            {"action": "scroll", "times": 4, "pause_ms": 600},
        ],
        model_instructions="""
BCG X / BCG CAREERS:
1. India filter on careers.bcg.com search-results.
2. Target: data scientist, ML engineer, software engineer, product manager in BCG X/BCG Gamma teams.
3. Offices: Bengaluru, Mumbai, Gurgaon.
""",
    ),
    "imc trading": CareerPageConfig(
        company="IMC Trading",
        career_url="https://www.imc.com/eu/careers/",
        portal_type="custom_imc",
        job_link_patterns=[
            r"https?://www\.imc\.com/[^/]+/careers/[^?\s]+",
            r"https?://[^/]*imc[^/]*\.wd\d+\.myworkdayjobs\.com/[^?\s]+",
        ],
        navigation_steps=[
            {"action": "goto", "url": "{career_url}"},
            {"action": "wait", "ms": 3000},
            {"action": "click_if_visible", "selector": "a:has-text('See all jobs'), a:has-text('View all')"},
            {"action": "wait", "ms": 2000},
            {"action": "scroll", "times": 4, "pause_ms": 600},
        ],
        model_instructions="""
IMC TRADING:
1. Careers: imc.com/eu/careers/ (global listings).
2. Look for: Quantitative Researcher, Software Engineer, Trader, Data Science.
3. Mumbai office exists — prioritize India-located roles.
""",
    ),
    "ebay": CareerPageConfig(
        company="eBay",
        career_url="https://jobs.ebayinc.com/us/en",
        portal_type="custom",
        job_link_patterns=[
            r"https?://jobs\.ebayinc\.com/us/en/job/[^?\s]+",
            r"https?://jobs\.ebayinc\.com/global/en/job/[^?\s]+",
        ],
        navigation_steps=[
            {"action": "goto", "url": "{career_url}"},
            {"action": "wait", "ms": 4000},
            {"action": "auto_search", "location": "India"},
            {"action": "wait", "ms": 3000},
            {"action": "scroll", "times": 4, "pause_ms": 600},
        ],
        model_instructions="""
EBAY CAREERS (Phenom People):
1. Portal: jobs.ebayinc.com/us/en
2. Enter keyword along with 'India' in search field.
3. Job URLs follow /job/{job_id}/{slug} format.
4. Target roles in Bengaluru/India: data scientist, analytics, engineering.
""",
    ),
}


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
        url = cfg.india_url or cfg.career_url
        result[cfg.company] = url
    return result


def get_all_navigation_instructions() -> str:
    """Combined navigation guide injected into LLM prompts."""
    sections = ["# Company Career Portal Navigation Guide\n"]
    for cfg in CAREER_PAGE_REGISTRY.values():
        sections.append(f"## {cfg.company}\nURL: {cfg.india_url or cfg.career_url}\n{cfg.model_instructions.strip()}\n")
    return "\n".join(sections)


def resolve_start_url(cfg: CareerPageConfig) -> str:
    return cfg.india_url or cfg.career_url
