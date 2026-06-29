from v2.agent.tools.coaching_matchup import get_coaching_matchup
from v2.agent.tools.head_to_head import get_head_to_head
from v2.agent.tools.injury_list import get_injury_list
from v2.agent.tools.ladder import get_ladder
from v2.agent.tools.lessons import get_lessons
from v2.agent.tools.recent_form import get_recent_form
from v2.agent.tools.spine_synergy import get_spine_synergy
from v2.agent.tools.team_sheet import get_team_sheet
from v2.agent.tools.trap_game import detect_trap_game
from v2.agent.tools.venue_profile import get_venue_profile
from v2.agent.tools.weather import get_weather
from v2.agent.tools.web_search import web_search

ALL_TOOLS = [
    get_team_sheet,
    get_recent_form,
    get_head_to_head,
    get_ladder,
    get_weather,
    get_injury_list,
    get_venue_profile,
    get_coaching_matchup,
    web_search,
    detect_trap_game,
    get_spine_synergy,
    get_lessons,
]
