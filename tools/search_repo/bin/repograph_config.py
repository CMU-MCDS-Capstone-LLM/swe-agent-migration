import os

def get_config():
    """
    Returns the configuration for the repository and output folder.
    """
    REPO_PATH = os.environ.get("ROOT")
    REPO_NAME = os.path.basename(REPO_PATH)
    if not REPO_PATH:
        raise ValueError("Environment variable 'ROOT' is not set.")
    config = {
        "repository": {
            "path": REPO_PATH
        },
        "output": {
            "folder": "/output/repograph/{}/".format(REPO_NAME),
        },
    }
    return config