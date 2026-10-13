"""Cohort scaling and reproducible submission probabilities without Docker."""

from collections import Counter

import pytest

from tests.functional.test_simulation import EXERCISES, exercise_order, success_attempt


@pytest.mark.parametrize("count", [1, 2, 3, 4, 99, 100, 101, 102, 205])
def test_every_student_visits_all_exercises_in_balanced_groups(count):
    journeys = [exercise_order(index, count) for index in range(count)]
    assert all(len(order) == len(set(order)) == 3 for order in journeys)
    assert all(set(order) == set(EXERCISES) for order in journeys)
    for round_index in range(3):
        groups = Counter(order[round_index] for order in journeys)
        sizes = [groups[exercise] for exercise in EXERCISES]
        assert sum(sizes) == count
        assert max(sizes) - min(sizes) <= 1


def test_default_cohort_uses_three_contiguous_groups_of_33():
    for first, last, exercise in [
        (0, 33, "hello-c"),
        (33, 66, "fibo-c"),
        (66, 99, "sum-c"),
    ]:
        assert all(
            exercise_order(index, 99)[0] == exercise for index in range(first, last)
        )


@pytest.mark.parametrize("index, count", [(0, 0), (-1, 99), (99, 99)])
def test_invalid_cohort_members_are_rejected(index, count):
    with pytest.raises(ValueError):
        exercise_order(index, count)


def test_probabilities_are_conditional_and_every_student_finishes():
    outcomes = [success_attempt(20261013, index, "hello-c") for index in range(10000)]
    assert outcomes == [
        success_attempt(20261013, index, "hello-c") for index in range(10000)
    ]
    assert set(outcomes) == {1, 2, 3}
    counts = Counter(outcomes)
    assert 0.31 < counts[1] / len(outcomes) < 0.36
    assert 0.47 < counts[2] / (counts[2] + counts[3]) < 0.53
    assert outcomes != [success_attempt(1, index, "hello-c") for index in range(10000)]


def test_student_outcomes_do_not_depend_on_worker_scheduling_or_cohort_size():
    pairs = [(index, exercise) for index in range(102) for exercise in EXERCISES]
    planned = {
        (index, exercise): success_attempt(7, index, exercise)
        for index, exercise in pairs
    }
    reverse = {
        (index, exercise): success_attempt(7, index, exercise)
        for index, exercise in reversed(pairs)
    }
    assert planned == reverse
    assert all(1 <= attempt <= 3 for attempt in planned.values())
