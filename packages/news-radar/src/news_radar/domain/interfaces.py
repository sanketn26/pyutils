from abc import ABC, abstractmethod
from collections.abc import Generator
from typing import Any


class Filter(ABC):
    '''
    Abstract base class for filters in the news radar domain for processing
    and filtering information bits.
    '''
    @abstractmethod
    def filter(self, data: Any) -> Any:
        pass

class Pipe(ABC):
    '''
    Abstract base class for pipes in the news radar domain for processing
    and transforming information bits.
    '''
    @abstractmethod
    def produce(self, conf: Any) -> Generator[Any]:
        pass

class Sink(ABC):
    '''
    Abstract base class for sinks in the news radar domain for consuming
    and storing information bits.
    '''
    @abstractmethod
    def consume(self, data: Any) -> None:
        pass

class Pipeline:
    '''
    Base class for pipelines in the news radar domain for orchestrating
    the flow of information bits through filters, pipes, and sinks.
    '''
    def __init__(self, pipe: Pipe, sink: Sink, filters: list[Filter] | None = None) -> None:
        self.filters = list(filters) if filters else []
        self.pipe = pipe
        self.sink = sink

    def add_filter(self, filter: Filter) -> None:
        '''
        Adds a filter to the pipeline.

        Parameters:
        filter (Filter): The filter to be added.
        '''
        self.filters.append(filter)

    def run(self, conf: Any) -> None:
        for data in self.pipe.produce(conf=conf):
            for filter in self.filters:
                data = filter.filter(data)
                if data is None:
                    break
            if data is None:
                continue
            self.sink.consume(data)
