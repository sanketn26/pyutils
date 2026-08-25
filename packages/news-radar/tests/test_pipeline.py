from collections.abc import Generator
from typing import Any

from news_radar.domain.interfaces import Filter, Pipe, Pipeline, Sink


class ListPipe(Pipe):
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def produce(self, conf: Any) -> Generator[Any]:
        yield from self.items


class AddFilter(Filter):
    def __init__(self, amount: int) -> None:
        self.amount = amount

    def filter(self, data: Any) -> Any:
        return data + self.amount


class DropEvenFilter(Filter):
    def filter(self, data: Any) -> Any:
        return None if data % 2 == 0 else data


class CollectSink(Sink):
    def __init__(self) -> None:
        self.consumed: list[Any] = []

    def consume(self, data: Any) -> None:
        self.consumed.append(data)


def test_pipeline_runs_data_through_filters_into_sink() -> None:
    sink = CollectSink()
    pipeline = Pipeline(ListPipe([1, 2, 3]), sink, filters=[AddFilter(10)])

    pipeline.run(conf=None)

    assert sink.consumed == [11, 12, 13]


def test_pipeline_with_no_filters_passes_data_through_unmodified() -> None:
    sink = CollectSink()
    pipeline = Pipeline(ListPipe([1, 2, 3]), sink)

    pipeline.run(conf=None)

    assert sink.consumed == [1, 2, 3]


def test_pipeline_skips_sink_when_a_filter_drops_the_item() -> None:
    sink = CollectSink()
    pipeline = Pipeline(ListPipe([1, 2, 3, 4]), sink, filters=[DropEvenFilter()])

    pipeline.run(conf=None)

    assert sink.consumed == [1, 3]


def test_pipeline_default_filters_are_not_shared_between_instances() -> None:
    sink_a = CollectSink()
    sink_b = CollectSink()
    pipeline_a = Pipeline(ListPipe([1]), sink_a)
    pipeline_b = Pipeline(ListPipe([1]), sink_b)

    pipeline_a.add_filter(AddFilter(100))
    pipeline_a.run(conf=None)
    pipeline_b.run(conf=None)

    assert sink_a.consumed == [101]
    assert sink_b.consumed == [1]


def test_add_filter_appends_to_existing_filter_list() -> None:
    sink = CollectSink()
    pipeline = Pipeline(ListPipe([1]), sink, filters=[AddFilter(1)])

    pipeline.add_filter(AddFilter(10))
    pipeline.run(conf=None)

    assert sink.consumed == [12]
