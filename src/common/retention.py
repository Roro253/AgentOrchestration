"""Retention deletion workflow for primary and derived task data."""

import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set

from src.common.metrics import metrics


@dataclass(frozen=True)
class RetentionRecord:
    store: str
    record_id: str
    data_class: str
    source_id: Optional[str] = None


@dataclass
class RetentionStore:
    name: str
    data_class: str
    derived: bool = False
    records: Dict[str, RetentionRecord] = field(default_factory=dict)

    def add(self, record_id: str, source_id: Optional[str] = None) -> None:
        self.records[record_id] = RetentionRecord(
            store=self.name,
            record_id=record_id,
            data_class=self.data_class,
            source_id=source_id,
        )

    def delete_for_sources(self, source_ids: Set[str]) -> List[str]:
        deleted = []
        for record_id, record in list(self.records.items()):
            target_id = record.source_id if self.derived else record.record_id
            if target_id in source_ids:
                deleted.append(record_id)
                self.records.pop(record_id, None)
        return deleted

    def stale_records(
        self,
        live_source_ids: Set[str],
    ) -> List[RetentionRecord]:
        if not self.derived:
            return []
        return [
            record
            for record in self.records.values()
            if record.source_id not in live_source_ids
        ]


@dataclass(frozen=True)
class DeletionManifestEntry:
    store: str
    data_class: str
    derived: bool
    record_ids: List[str]


@dataclass
class DeletionCompletion:
    workspace_id: str
    requested_ids: List[str]
    completed_at: float
    stores: List[DeletionManifestEntry]

    def data_classes(self) -> Set[str]:
        return {entry.data_class for entry in self.stores}


@dataclass(frozen=True)
class DeletionVerification:
    workspace_id: str
    verified_at: float
    complete: bool
    remaining_record_ids: Dict[str, List[str]]


class RetentionDeletionService:
    def __init__(self, stores: Iterable[RetentionStore]):
        self._stores = {store.name: store for store in stores}
        self._completions: Dict[str, DeletionCompletion] = {}

    def build_manifest(
        self,
        workspace_id: str,
        source_ids: Iterable[str],
    ) -> DeletionCompletion:
        source_id_set = set(source_ids)
        entries = []
        for store in self._stores.values():
            record_ids = self._matching_record_ids(store, source_id_set)
            entries.append(
                DeletionManifestEntry(
                    store=store.name,
                    data_class=store.data_class,
                    derived=store.derived,
                    record_ids=record_ids,
                )
            )
        return DeletionCompletion(
            workspace_id=workspace_id,
            requested_ids=sorted(source_id_set),
            completed_at=0.0,
            stores=entries,
        )

    def delete_workspace_data(
        self,
        workspace_id: str,
        source_ids: Iterable[str],
    ) -> DeletionCompletion:
        source_id_set = set(source_ids)
        entries = []
        for store in self._stores.values():
            deleted_ids = store.delete_for_sources(source_id_set)
            entries.append(
                DeletionManifestEntry(
                    store=store.name,
                    data_class=store.data_class,
                    derived=store.derived,
                    record_ids=sorted(deleted_ids),
                )
            )
            metrics.increment(
                f"retention.deleted.{store.data_class}",
                len(deleted_ids),
            )

        completion = DeletionCompletion(
            workspace_id=workspace_id,
            requested_ids=sorted(source_id_set),
            completed_at=time.time(),
            stores=entries,
        )
        self._completions[workspace_id] = completion
        return completion

    def reconcile_derived_data(self, workspace_id: str) -> DeletionCompletion:
        primary_ids = self._live_primary_ids()
        stale_source_ids = {
            record.source_id
            for store in self._stores.values()
            for record in store.stale_records(primary_ids)
            if record.source_id
        }
        completion = self.delete_workspace_data(workspace_id, stale_source_ids)
        metrics.increment(
            "retention.reconciled.stale_sources",
            len(stale_source_ids),
        )
        return completion

    def completion_for(
        self,
        workspace_id: str,
    ) -> Optional[DeletionCompletion]:
        return self._completions.get(workspace_id)

    def verify_completion(
        self,
        completion: DeletionCompletion,
    ) -> DeletionVerification:
        source_id_set = set(completion.requested_ids)
        remaining: Dict[str, List[str]] = {}
        for entry in completion.stores:
            store = self._stores.get(entry.store)
            if not store:
                remaining[entry.store] = completion.requested_ids
                continue

            record_ids = self._matching_record_ids(store, source_id_set)
            if record_ids:
                remaining[entry.store] = record_ids

        return DeletionVerification(
            workspace_id=completion.workspace_id,
            verified_at=time.time(),
            complete=not remaining,
            remaining_record_ids=remaining,
        )

    def _matching_record_ids(
        self,
        store: RetentionStore,
        source_ids: Set[str],
    ) -> List[str]:
        matches = []
        for record_id, record in store.records.items():
            target_id = record.source_id if store.derived else record.record_id
            if target_id in source_ids:
                matches.append(record_id)
        return sorted(matches)

    def _live_primary_ids(self) -> Set[str]:
        return {
            record.record_id
            for store in self._stores.values()
            if not store.derived
            for record in store.records.values()
        }
