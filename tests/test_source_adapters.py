from __future__ import annotations

from datetime import date

from paper_radar.sources.acl_anthology import ACLAnthologySource
from paper_radar.sources.crossref_works import CrossrefWorksSource
from paper_radar.sources.cvf import CVFSource
from paper_radar.sources.europepmc import EuropePMCSource
from paper_radar.sources.neurips_proceedings import NeurIPSProceedingsSource
from paper_radar.sources.openalex import OpenAlexSource
from paper_radar.sources.openreview import OpenReviewSource
from paper_radar.sources.pmlr import PMLRSource
from paper_radar.sources.rss_proceedings import RSSProceedingsSource


class FakeJSONClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_json(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.payload


class FakeResponse:
    def __init__(self, text: str = "", content: bytes | None = None):
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")


class FakeHTMLClient:
    def __init__(self, body: str):
        self.body = body
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse(text=self.body, content=self.body.encode("utf-8"))


def test_europepmc_normalizes_core_fields():
    payload = {
        "resultList": {
            "result": [
                {
                    "id": "12345",
                    "source": "MED",
                    "doi": "10.1016/j.slast.2026.100458",
                    "pmid": "42641793",
                    "title": "A Scalable High-Density Microwell Assay",
                    "authorString": "Karoliina S, Shiska R",
                    "journalTitle": "SLAS Technol",
                    "pubYear": 2026,
                    "firstPublicationDate": "2026-08-25",
                    "abstractText": "We present a method.",
                    "citedByCount": 3,
                }
            ]
        }
    }
    source = EuropePMCSource(FakeJSONClient(payload))
    papers = source.fetch(["single cell"], date(2026, 8, 1), date(2026, 8, 31), 20)
    assert len(papers) == 1
    paper = papers[0]
    assert paper.title == "A Scalable High-Density Microwell Assay"
    assert paper.doi == "10.1016/j.slast.2026.100458"
    assert paper.pubmed_id == "42641793"
    assert paper.venue == "SLAS Technol"
    assert paper.citation_count == 3
    assert paper.authors == ["Karoliina S", "Shiska R"]
    assert paper.source == "europepmc"


def test_openalex_reconstructs_abstract_and_ids():
    payload = {
        "results": [
            {
                "id": "https://openalex.org/W123",
                "doi": "https://doi.org/10.1177/1",
                "title": "Bridging language and action",
                "publication_date": "2026-07-29",
                "cited_by_count": 1,
                "primary_location": {
                    "landing_page_url": "https://doi.org/10.1177/1",
                    "source": {"display_name": "The International Journal of Robotics Research"},
                },
                "ids": {"openalex": "https://openalex.org/W123"},
                "abstract_inverted_index": {"We": [0], "present": [1], "a": [2], "method": [3]},
                "authorships": [{"author": {"display_name": "Jane Doe"}}],
            }
        ]
    }
    source = OpenAlexSource(FakeJSONClient(payload))
    papers = source.search(["robot"], date(2026, 6, 1), date(2026, 8, 31), 10)
    assert len(papers) == 1
    paper = papers[0]
    assert paper.openalex_id == "W123"
    assert paper.doi == "10.1177/1"
    assert paper.abstract == "We present a method"
    assert paper.venue == "The International Journal of Robotics Research"
    assert paper.authors == ["Jane Doe"]
    assert paper.citation_count == 1


def test_openreview_filters_withdrawn_and_out_of_venue():
    payload = {
        "notes": [
            {
                "id": "abc",
                "cdate": 1780000000000,
                "content": {
                    "title": {"value": "Diffusion^2"},
                    "abstract": {"value": "We model RF signals."},
                    "venue": {"value": "ICLR 2026 Conference Withdrawn Submission"},
                    "authors": {"value": ["A. One", "B. Two"]},
                },
            },
            {
                "id": "def",
                "cdate": 1780000000000,
                "content": {
                    "title": {"value": "A New Flow Matching Method"},
                    "abstract": {"value": "We propose a new method."},
                    "venue": {"value": "ICLR 2026 Conference"},
                    "authors": {"value": ["C. Three"]},
                },
            },
        ]
    }
    source = OpenReviewSource(FakeJSONClient(payload))
    papers = source.search(
        ["flow matching"], date(2020, 1, 1), date(2030, 1, 1), 10, venues=("ICLR",)
    )
    assert len(papers) == 1
    assert papers[0].title == "A New Flow Matching Method"
    assert papers[0].authors == ["C. Three"]


def test_crossref_works_scopes_by_container_title():
    payload = {
        "message": {
            "items": [
                {
                    "DOI": "10.1038/s41592-1",
                    "title": ["A unified formulation for perturbation dynamics"],
                    "container-title": ["Nature Methods"],
                    "published": {"date-parts": [[2026, 8, 20]]},
                    "author": [{"given": "Jane", "family": "Doe"}],
                    "URL": "https://doi.org/10.1038/s41592-1",
                    "is-referenced-by-count": 4,
                }
            ]
        }
    }
    source = CrossrefWorksSource(FakeJSONClient(payload))
    papers = source.fetch(["Nature Methods"], date(2026, 8, 1), date(2026, 8, 31), 20)
    assert len(papers) == 1
    paper = papers[0]
    assert paper.doi == "10.1038/s41592-1"
    assert paper.venue == "Nature Methods"
    assert paper.authors == ["Jane Doe"]
    assert paper.citation_count == 4


PMLR_BODY = """
<div class="paper">
  <p class="title">Adaptively Perturbed Mirror Descent for Learning in Games</p>
  <p class="details">
    <span class="authors">Kenshi Abe,&nbsp;Kaito Ariu</span>;
    <span class="info"><i>Proceedings</i>, PMLR 235:31-80</span>
  </p>
  <p class="links">
    [<a href="https://proceedings.mlr.press/v235/abe24a.html">abs</a>][<a href="x">pdf</a>]
  </p>
</div>
"""


def test_pmlr_parses_paper_blocks():
    source = PMLRSource(FakeHTMLClient(PMLR_BODY))
    papers = source.fetch(235, "ICML", 2024)
    assert len(papers) == 1
    paper = papers[0]
    assert paper.title == "Adaptively Perturbed Mirror Descent for Learning in Games"
    assert paper.authors == ["Kenshi Abe", "Kaito Ariu"]
    assert paper.venue == "ICML"
    assert paper.year == 2024
    assert paper.paper_url == "https://proceedings.mlr.press/v235/abe24a.html"


NEURIPS_BODY = (
    '<a href="/paper_files/paper/2024/hash/abc123-Abstract-Conference.html">'
    "MicroAdam: Accurate Adaptive Optimization</a>"
)


def test_neurips_proceedings_parses_index_links():
    source = NeurIPSProceedingsSource(FakeHTMLClient(NEURIPS_BODY))
    papers = source.fetch(2024)
    assert len(papers) == 1
    assert papers[0].title == "MicroAdam: Accurate Adaptive Optimization"
    assert papers[0].venue == "NeurIPS"
    assert papers[0].year == 2024


CVF_BODY = (
    '<dt class="ptitle"><br><a href="/content/CVPR2024/html/Xie_CityDreamer_paper.html">'
    "CityDreamer: Compositional Generative Model</a></dt>"
)


def test_cvf_parses_title_blocks():
    source = CVFSource(FakeHTMLClient(CVF_BODY))
    papers = source.fetch("CVPR", 2024)
    assert len(papers) == 1
    assert papers[0].title == "CityDreamer: Compositional Generative Model"
    assert papers[0].venue == "CVPR"


ACL_XML = """<?xml version='1.0' encoding='UTF-8'?>
<collection id="2025.acl">
  <volume id="long">
    <paper id="1">
      <title><fixed-case>E</fixed-case>comScriptBench</title>
      <author><first>Weiqi</first><last>Wang</last></author>
      <author><first>Limeng</first><last>Cui</last></author>
      <abstract>Goal-oriented script planning.</abstract>
      <url hash="a77aa6a5">2025.acl-long.1</url>
      <doi>10.18653/v1/2025.acl-long.1</doi>
    </paper>
  </volume>
</collection>
"""


def test_acl_anthology_parses_xml_with_abstract_and_authors():
    source = ACLAnthologySource(FakeHTMLClient(ACL_XML))
    papers = source.fetch("acl", "ACL", 2025)
    assert len(papers) == 1
    paper = papers[0]
    assert paper.title == "EcomScriptBench"
    assert paper.authors == ["Weiqi Wang", "Limeng Cui"]
    assert paper.abstract == "Goal-oriented script planning."
    assert paper.doi == "10.18653/v1/2025.acl-long.1"
    assert paper.paper_url == "https://aclanthology.org/2025.acl-long.1/"


RSS_BODY = """
<table id="myTable">
 <tr session="Manipulation 1">
    <td width="5%">1</td>
    <td width="15%">Manipulation 1</td>
    <td width="40%">
      <a href="/program/papers/1/">
        <b>One-Shot Real-World Demonstration Synthesis</b>
      </a>
    </td>
    <td width="40%">
      Huayi Zhou, Kui Jia
      <div class="content" style="display:none;">Huayi Zhou, Kui Jia</div>
    </td>
  </tr>
</table>
"""


def test_rss_proceedings_parses_table_rows():
    source = RSSProceedingsSource(FakeHTMLClient(RSS_BODY))
    papers = source.fetch(year=2026)
    assert len(papers) == 1
    paper = papers[0]
    assert paper.title == "One-Shot Real-World Demonstration Synthesis"
    assert paper.authors == ["Huayi Zhou", "Kui Jia"]
    assert paper.venue == "RSS"
    assert paper.year == 2026
