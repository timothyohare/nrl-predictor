Feature: Gate write path
  The async prediction/scoring write path runs correctly against the seeded
  tables (see write_path_setup.py — canonical history rounds 1-3, draw kickOff
  rows for rounds 20-29). Each scenario owns its own round number so they stay
  independent within one gate run.

  Scenario: Orchestrator predict loop writes an OK prediction per drawn match
    Given a drawn round 20 of 3 matches
    When the stats predictor runs for the round
    Then every match has an OK prediction row
    And every prediction is stamped prompt_version "stats-elo-v1"
    And every prediction is generation 1

  Scenario: Re-running the predict loop supersedes rather than overwrites
    Given a drawn round 21 of 3 matches
    When the stats predictor runs for the round
    And the stats predictor runs for the round again
    Then every match has 2 prediction rows
    And the newest prediction per match is generation 2

  Scenario: A failing match writes a FAILED row without blocking the round
    Given a drawn round 22 of 3 matches
    And the model raises for the first match
    When the stats predictor runs for the round
    Then the first match has a FAILED prediction row
    And the other 2 matches have an OK prediction row

  Scenario: Coverage check flags an under-predicted round and emits the shortfall
    Given a drawn round 23 of 3 matches
    And only 2 of the 3 matches are predicted
    When the coverage check runs for the round
    Then it reports 1 missing match
    And it emits a MissingPredictions metric of 1

  Scenario: Scoring scores the round and fires the retrospective trigger
    Given a drawn round 24 of 3 matches
    And the round is predicted
    And a full-time result exists for the first match
    When the scoring lambda runs for the first match
    Then the scoring lambda returns OK
    And a scored result row carries the round number and a brier component
    And the round and season metric aggregates are written
    And the retrospective lambda was invoked once for the first match
