import json

class ProjectConfig:
    def __init__(self, gitlab_url: str, gitlab_branch: str, public_url: str, dast_params: str, team: str):
        self.gitlab_url     = gitlab_url
        self.gitlab_branch  = gitlab_branch
        self.public_url     = public_url
        self.dast_params    = dast_params
        self.team           = team

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            gitlab_url      = data.get("gitlab_url", ""),
            gitlab_branch   = data.get("gitlab_branch", ""),
            public_url      = data.get("public_url", ""),
            dast_params     = data.get("dast_params", ""),
            team            = data.get("team", "")
        )

    @classmethod
    def from_file(cls, filepath: str):
        with open(filepath, "r") as f:
            projects_data = json.load(f)
        return [cls.from_dict(project) for project in projects_data]
