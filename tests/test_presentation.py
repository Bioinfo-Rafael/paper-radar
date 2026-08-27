from paper_radar.presentation import group_papers
from tests.conftest import make_paper


def test_bioinfo_major_journals_and_direct_interest(config):
    major = make_paper(title="Major", venue="Nature Methods")
    direct = make_paper(title="Direct", venue="bioRxiv", matched_criteria=["rna-velocity"])
    groups = group_papers("bioinfo", [major, direct], config.venues["bioinfo"])
    assert [(group.name, group.papers) for group in groups] == [
        ("🌟 Major Journals", [major]),
        ("🎯 Direct Interest", [direct]),
    ]


def test_ml_grouping_uses_text_and_criteria_and_preserves_ranking():
    first = make_paper(title="Flow Matching Without Simulation")
    second = make_paper(title="Diffusion Theory", matched_criteria=["theory"])
    transformer = make_paper(title="A Transformer", matched_criteria=["architecture"])
    groups = group_papers("ml", [first, second, transformer])
    assert groups[0].name == "🌫 Diffusion / Score / Flow"
    assert groups[0].papers == [first, second]
    assert groups[1].name == "🔤 Autoregressive / Transformer"
    assert groups[1].papers == [transformer]


def test_frontier_priority_and_no_duplicates():
    multi = make_paper(
        title="A self-improving world model agent",
        matched_criteria=["self-improvement", "world-model", "agent"],
    )
    reasoning = make_paper(title="Reasoning", matched_criteria=["reasoning"])
    groups = group_papers("frontier", [multi, reasoning])
    assert groups[0].name == "🧠 Self-Improvement / AI Scientist"
    assert groups[0].papers == [multi]
    assert groups[1].name == "💭 Reasoning / Test-Time Compute"
    assert [paper for group in groups for paper in group.papers] == [multi, reasoning]


def test_empty_groups_are_omitted_and_other_is_used():
    other = make_paper(title="Unclassified method")
    groups = group_papers("ml", [other])
    assert [(group.name, group.papers) for group in groups] == [("📦 Other ML", [other])]
