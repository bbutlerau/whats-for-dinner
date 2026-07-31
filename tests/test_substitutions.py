"""Tests for merge suggestions and saved substitutions.

Both are places where being confidently wrong is worse than being unhelpful: a
bad suggestion is a bad merge one tap away, and a bad saved rule applies itself
silently to every future import. The cutoffs and the "always" flag are the two
things worth pinning down.
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.ingredients.store import (
    forget_substitution,
    remember_substitution,
    resolve_line,
    set_alias,
    suggest_merge_targets,
)
from app.models import PantryItem, SubstitutionRule


def _item(session: Session, line: str) -> PantryItem:
    _, item = resolve_line(session, line)
    session.commit()
    return item


def _all_items(session: Session) -> list[PantryItem]:
    return list(session.exec(select(PantryItem)).all())


class TestSuggestMergeTargets:
    def test_same_base_name_with_a_different_form_is_the_top_suggestion(self, session):
        bare = _item(session, "1 tsp basil")
        dried = _item(session, "1 tsp dried basil")
        _item(session, "2 onions")

        suggestions = suggest_merge_targets(session, bare, _all_items(session))
        assert suggestions[0].id == dried.id

    def test_a_near_miss_spelling_is_suggested(self, session):
        item = _item(session, "1 bunch corriander")
        proper = _item(session, "1 bunch coriander")

        suggestions = suggest_merge_targets(session, item, _all_items(session))
        assert proper.id in [s.id for s in suggestions]

    def test_unrelated_items_are_not_suggested(self, session):
        carrot = _item(session, "2 carrots")
        _item(session, "500 g invented beef mince")
        _item(session, "1 tin invented beans")

        assert suggest_merge_targets(session, carrot, _all_items(session)) == []

    def test_an_item_never_suggests_itself(self, session):
        item = _item(session, "1 tsp basil")
        suggestions = suggest_merge_targets(session, item, _all_items(session))
        assert item.id not in [s.id for s in suggestions]

    def test_already_merged_items_are_not_offered_as_targets(self, session):
        bare = _item(session, "1 tsp basil")
        dried = _item(session, "1 tsp dried basil")
        fresh = _item(session, "1 tsp fresh basil")

        # Once fresh basil is merged into dried, it is no longer somewhere you
        # can merge a third item — that would build a chain.
        set_alias(session, fresh, dried)
        session.commit()

        suggestions = suggest_merge_targets(session, bare, _all_items(session))
        assert fresh.id not in [s.id for s in suggestions]

    def test_a_partial_word_is_not_treated_as_a_match(self, session):
        """Corn and cornflour are different things to own."""
        corn = _item(session, "1 tin corn")
        _item(session, "2 tbsp cornflour")

        assert suggest_merge_targets(session, corn, _all_items(session)) == []

    def test_suggestions_are_capped(self, session):
        bare = _item(session, "1 tsp basil")
        for line in ["1 tsp dried basil", "1 tsp fresh basil", "1 tsp frozen basil"]:
            _item(session, line)

        assert len(suggest_merge_targets(session, bare, _all_items(session), limit=2)) == 2


class TestSavedSubstitutions:
    def test_a_saved_rule_merges_a_future_item_automatically(self, session):
        coriander = _item(session, "1 bunch coriander")
        cilantro = _item(session, "1 bunch cilantro")
        set_alias(session, cilantro, coriander)
        remember_substitution(session, cilantro, coriander)
        session.commit()

        # Simulate the item being gone and reintroduced by a later import.
        session.delete(cilantro)
        session.commit()

        _, reimported = resolve_line(session, "2 bunches cilantro")
        session.commit()
        assert reimported.alias_of_id == coriander.id

    def test_without_a_saved_rule_a_future_item_stays_separate(self, session):
        parsley = _item(session, "1 bunch parsley")
        choice = _item(session, "1 tbsp basil or parsley")
        # Merged for this week only — no rule saved, which is the "it's a
        # judgement call each time" case.
        set_alias(session, choice, parsley)
        session.commit()

        session.delete(choice)
        session.commit()

        _, reimported = resolve_line(session, "1 tbsp basil or parsley")
        session.commit()
        assert reimported.alias_of_id is None

    def test_re_saving_replaces_the_earlier_rule(self, session):
        first = _item(session, "1 bunch coriander")
        second = _item(session, "1 bunch fresh coriander")
        cilantro = _item(session, "1 bunch cilantro")

        remember_substitution(session, cilantro, first)
        remember_substitution(session, cilantro, second)
        session.commit()

        rules = session.exec(
            select(SubstitutionRule).where(SubstitutionRule.source_key == cilantro.key)
        ).all()
        assert len(rules) == 1
        assert rules[0].target_key == second.key

    def test_unmerging_forgets_the_rule(self, session):
        coriander = _item(session, "1 bunch coriander")
        cilantro = _item(session, "1 bunch cilantro")
        remember_substitution(session, cilantro, coriander)
        session.commit()

        forget_substitution(session, cilantro)
        session.commit()

        assert session.exec(select(SubstitutionRule)).all() == []

    def test_a_rule_whose_target_is_gone_leaves_the_item_alone(self, session):
        coriander = _item(session, "1 bunch coriander")
        cilantro = _item(session, "1 bunch cilantro")
        remember_substitution(session, cilantro, coriander)
        session.commit()

        session.delete(cilantro)
        session.delete(coriander)
        session.commit()

        _, reimported = resolve_line(session, "1 bunch cilantro")
        session.commit()
        # No target to point at, so it stands on its own rather than erroring.
        assert reimported.alias_of_id is None


class TestSynonymSuggestions:
    """The cases string similarity cannot reach."""

    def test_a_known_synonym_is_suggested(self, session):
        cilantro = _item(session, "1 bunch cilantro")
        coriander = _item(session, "1 bunch coriander")

        suggestions = suggest_merge_targets(session, cilantro, _all_items(session))
        assert [s.id for s in suggestions] == [coriander.id]

    def test_a_synonym_pair_with_no_string_similarity_at_all(self, session):
        # zucchini and courgette score 0.12 against each other.
        zucchini = _item(session, "2 zucchini")
        courgette = _item(session, "2 courgettes")

        suggestions = suggest_merge_targets(session, zucchini, _all_items(session))
        assert courgette.id in [s.id for s in suggestions]

    def test_the_synonym_table_is_symmetric(self, session):
        eggplant = _item(session, "1 eggplant")
        aubergine = _item(session, "1 aubergine")

        assert aubergine.id in [
            s.id for s in suggest_merge_targets(session, eggplant, _all_items(session))
        ]
        assert eggplant.id in [
            s.id for s in suggest_merge_targets(session, aubergine, _all_items(session))
        ]

    def test_a_rhyming_word_is_not_suggested(self, session):
        """carrot/parrot scores 0.83 — the reason the fuzzy cutoff is 0.9."""
        carrot = _item(session, "2 carrots")
        _item(session, "1 invented parrot")

        assert suggest_merge_targets(session, carrot, _all_items(session)) == []

    def test_a_real_misspelling_still_gets_through(self, session):
        misspelt = _item(session, "1 bunch corriander")
        proper = _item(session, "1 bunch coriander")

        suggestions = suggest_merge_targets(session, misspelt, _all_items(session))
        assert proper.id in [s.id for s in suggestions]

    def test_a_form_variant_outranks_a_synonym(self, session):
        bare = _item(session, "1 bunch coriander")
        dried = _item(session, "1 tsp dried coriander")
        _item(session, "1 bunch cilantro")

        suggestions = suggest_merge_targets(session, bare, _all_items(session))
        assert suggestions[0].id == dried.id
