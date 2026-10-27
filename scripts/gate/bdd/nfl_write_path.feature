Feature: NFL orchestrator write path
  The daily NFL orchestrator ingests the nflverse schedule (the fixture CSV over
  file://), upserts the current season into nfl_games and predicts the next week
  into nfl_predictions, against DynamoDB Local (see nfl_setup.py). Each scenario
  starts from empty NFL tables so they stay independent within one gate run.

  Background:
    Given empty NFL tables
    And the nflverse fixture CSV is the data source
    And the clock is frozen before the 2026 week 8 kickoffs

  Scenario: The orchestrator predicts exactly the next week, idempotently
    When the NFL orchestrator runs
    Then nfl_predictions holds exactly the week-8 games
    And every NFL prediction is an OK live row stamped "nfl-elo-v1" with scraped_at
    And nfl_games holds the 2026 games, each with scraped_at
    And it emits an UnpredictedGames metric of 0
    When the NFL orchestrator runs again
    Then nfl_predictions holds exactly the week-8 games

  Scenario: The backfill labels earlier weeks and never shadows a live row
    Given the NFL orchestrator has run
    When the NFL backfill runs
    Then the 2026 weeks 5 and 7 games have backfilled rows
    And the week-8 games still have only their live row
