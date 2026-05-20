from src.common.retention import RetentionDeletionService, RetentionStore


class TestRetentionDeletionService:
    def setup_method(self):
        self.artifacts = RetentionStore("artifact_store", "primary_artifacts")
        self.embeddings = RetentionStore(
            "embedding_store",
            "derived_embeddings",
            derived=True,
        )
        self.indexes = RetentionStore(
            "search_index",
            "derived_indexes",
            derived=True,
        )
        self.service = RetentionDeletionService(
            [self.artifacts, self.embeddings, self.indexes]
        )

    def test_deletion_manifest_enumerates_primary_and_derived_stores(self):
        self.artifacts.add("task-a")
        self.embeddings.add("embed-a", source_id="task-a")
        self.indexes.add("index-a", source_id="task-a")

        manifest = self.service.build_manifest("workspace-1", ["task-a"])

        assert manifest.workspace_id == "workspace-1"
        assert manifest.requested_ids == ["task-a"]
        assert manifest.data_classes() == {
            "primary_artifacts",
            "derived_embeddings",
            "derived_indexes",
        }
        assert {entry.store for entry in manifest.stores} == {
            "artifact_store",
            "embedding_store",
            "search_index",
        }

    def test_delete_workspace_data_removes_primary_and_derived_records(self):
        self.artifacts.add("task-a")
        self.artifacts.add("task-b")
        self.embeddings.add("embed-a", source_id="task-a")
        self.embeddings.add("embed-b", source_id="task-b")
        self.indexes.add("index-a", source_id="task-a")

        completion = self.service.delete_workspace_data(
            "workspace-1",
            ["task-a"],
        )

        assert "task-a" not in self.artifacts.records
        assert "embed-a" not in self.embeddings.records
        assert "index-a" not in self.indexes.records
        assert "task-b" in self.artifacts.records
        assert "embed-b" in self.embeddings.records
        assert completion.completed_at > 0
        assert self.service.completion_for("workspace-1") == completion
        completed = {
            entry.data_class: entry.record_ids
            for entry in completion.stores
        }
        assert completed["primary_artifacts"] == ["task-a"]
        assert completed["derived_embeddings"] == ["embed-a"]
        assert completed["derived_indexes"] == ["index-a"]

    def test_reconcile_removes_stale_derived_records(self):
        self.artifacts.add("task-live")
        self.embeddings.add("embed-live", source_id="task-live")
        self.embeddings.add("embed-stale", source_id="task-deleted")
        self.indexes.add("index-stale", source_id="task-deleted")

        completion = self.service.reconcile_derived_data("workspace-1")

        assert "embed-live" in self.embeddings.records
        assert "embed-stale" not in self.embeddings.records
        assert "index-stale" not in self.indexes.records
        completed = {
            entry.data_class: entry.record_ids
            for entry in completion.stores
        }
        assert completed["primary_artifacts"] == []
        assert completed["derived_embeddings"] == ["embed-stale"]
        assert completed["derived_indexes"] == ["index-stale"]

    def test_repeated_deletion_records_empty_store_completion(self):
        self.artifacts.add("task-a")
        self.artifacts.add("task-live")
        self.embeddings.add("embed-a", source_id="task-a")
        self.embeddings.add("embed-live", source_id="task-live")
        self.indexes.add("index-a", source_id="task-a")

        first_completion = self.service.delete_workspace_data(
            "workspace-1",
            ["task-a"],
        )
        second_completion = self.service.delete_workspace_data(
            "workspace-1",
            ["task-a", "task-missing"],
        )

        assert self.service.verify_completion(first_completion).complete
        assert self.service.verify_completion(second_completion).complete
        assert "task-live" in self.artifacts.records
        assert "embed-live" in self.embeddings.records
        completed = {
            entry.data_class: entry.record_ids
            for entry in second_completion.stores
        }
        assert completed["primary_artifacts"] == []
        assert completed["derived_embeddings"] == []
        assert completed["derived_indexes"] == []
        assert second_completion.requested_ids == ["task-a", "task-missing"]

    def test_verify_completion_detects_incomplete_derived_store(self):
        self.artifacts.add("task-a")
        self.embeddings.add("embed-a", source_id="task-a")
        completion = self.service.delete_workspace_data(
            "workspace-1",
            ["task-a"],
        )
        self.indexes.add("index-stale", source_id="task-a")

        verification = self.service.verify_completion(completion)

        assert not verification.complete
        assert verification.workspace_id == "workspace-1"
        assert verification.remaining_record_ids == {
            "search_index": ["index-stale"],
        }
