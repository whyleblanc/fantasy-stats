from dataclasses import dataclass
from typing import Dict, List, Any


@dataclass
class WeekTeamStatsPayload:
    teamId: int
    teamName: str
    rank: int
    totalZ: float
    perCategoryZ: Dict[str, float]
    isLeagueAverage: bool = False

    def to_json(self) -> Dict[str, Any]:
        return {
            "teamId": self.teamId,
            "teamName": self.teamName,
            "rank": self.rank,
            "totalZ": self.totalZ,
            "perCategoryZ": self.perCategoryZ,
            "isLeagueAverage": self.isLeagueAverage,
        }