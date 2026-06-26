# tests/test_tiers.py
from ctc.accounting.tiers import TierInput, assign_tiers


def _tiers(results):
    return {r.user_id: r.tier for r in results}


def test_four_positives_one_per_quartile():
    entries = [
        TierInput("a", "A", 400, 0),
        TierInput("b", "B", 300, 0),
        TierInput("c", "C", 200, 0),
        TierInput("d", "D", 100, 0),
    ]
    assert _tiers(assign_tiers(entries)) == {
        "a": "aristocrat", "b": "baron", "c": "bourgeois", "d": "commoner",
    }


def test_single_positive_is_aristocrat():
    assert _tiers(assign_tiers([TierInput("a", "A", 500, 0)])) == {"a": "aristocrat"}


def test_two_positives_skip_to_bourgeois():
    entries = [TierInput("a", "A", 500, 0), TierInput("b", "B", 100, 0)]
    assert _tiers(assign_tiers(entries)) == {"a": "aristocrat", "b": "bourgeois"}


def test_eight_positives_two_per_quartile():
    entries = [TierInput(str(i), str(i), (8 - i) * 100, 0) for i in range(8)]
    got = _tiers(assign_tiers(entries))
    assert [got[str(i)] for i in range(8)] == [
        "aristocrat", "aristocrat", "baron", "baron",
        "bourgeois", "bourgeois", "commoner", "commoner",
    ]


def test_negatives_split_most_negative_is_beggar():
    entries = [TierInput("a", "A", 0, 100), TierInput("b", "B", 0, 50)]
    assert _tiers(assign_tiers(entries)) == {"a": "beggar", "b": "peasant"}


def test_three_negatives_two_beggars_one_peasant():
    entries = [
        TierInput("a", "A", 0, 100),
        TierInput("b", "B", 0, 60),
        TierInput("c", "C", 0, 20),
    ]
    assert _tiers(assign_tiers(entries)) == {"a": "beggar", "b": "beggar", "c": "peasant"}


def test_zero_activity_is_newcomer():
    assert _tiers(assign_tiers([TierInput("a", "A", 0, 0)])) == {"a": "newcomer"}


def test_net_zero_with_activity_is_positive_not_beggar():
    # gave back exactly what was taken -> counts as positive group
    assert _tiers(assign_tiers([TierInput("a", "A", 100, 100)])) == {"a": "aristocrat"}


def test_ties_broken_by_name_and_sorted_by_net_desc():
    entries = [
        TierInput("z", "Zed", 100, 0),
        TierInput("a", "Ann", 100, 0),
        TierInput("m", "Moe", 0, 50),
    ]
    results = assign_tiers(entries)
    # net desc, ties by name asc; negatives after positives; newcomers last
    assert [r.user_id for r in results] == ["a", "z", "m"]
    assert results[0].net == 100 and results[2].net == -50


def test_newcomers_appended_last():
    entries = [
        TierInput("n", "New", 0, 0),
        TierInput("g", "Giver", 200, 0),
    ]
    results = assign_tiers(entries)
    assert [r.user_id for r in results] == ["g", "n"]
    assert results[1].tier == "newcomer"
