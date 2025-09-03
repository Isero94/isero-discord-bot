import importlib

MODULES = [
    'bot',
    'bot.config',
    'cogs.agent.agent_gate',
    'cogs.watchers.keyword_watch',
    'utils.text',
]

def test_all_modules_importable():
    for name in MODULES:
        importlib.import_module(name)
