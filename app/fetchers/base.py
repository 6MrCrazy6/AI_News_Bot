import abc

class BaseFetcher(abc.ABC):
    def __init__(self, source_id, url, lang):
        self.source_id = source_id
        self.url = url
        self.lang = lang

    @abc.abstractmethod
    async def fetch(self):
        pass
