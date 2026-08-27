defmodule PowlPlatformTest do
  use ExUnit.Case, async: true

  defmodule FakeExecutor do
    @behaviour PowlPlatform.Executor

    @impl true
    def run(request) do
      run_id = Map.get(request, :run_id, Map.get(request, "run_id"))
      workflow_id = Map.get(request, :workflow_id, Map.get(request, "workflow_id"))

      {:ok,
       %{
         "protocol" => "powl-paas/1",
         "execution_mode" => "REPLAY_ONLY",
         "receipt" => %{
           "run_id" => run_id,
           "workflow_id" => workflow_id,
           "model_digest" => String.duplicate("a", 64),
           "standing" => "ALIVE",
           "receipt_digest" => String.duplicate("b", 64),
           "steps" => [],
           "replayed" => false
         }
       }}
    end
  end

  test "Reactor constructs intent without manufacturing DO authority" do
    request = %{
      run_id: "run-1",
      workflow_id: "wf-1",
      model_document: %{"format" => "powl-json"},
      execution_mode: "REPLAY_ONLY"
    }

    assert {:ok, result} = PowlPlatform.run(request, executor: FakeExecutor)
    assert result.intent.authority == "CONSTRUCT_ONLY"
    assert result.authority == "BRCE_BOUNDARY"
    assert result.standing == "ALIVE"
  end

  test "fresh DO through the replay bridge is refused before execution" do
    request = %{
      run_id: "run-1",
      workflow_id: "wf-1",
      model_document: %{},
      execution_mode: "FRESH_DO"
    }

    assert {:error, error} = PowlPlatform.run(request, executor: FakeExecutor)
    assert inspect(error) =~ "UNSUPPORTED_EXECUTION_MODE"
  end

  test "AshR2RML manufactures deterministic ontology, SHACL and R2RML projections" do
    assert {:ok, first} = PowlPlatform.Semantics.bundle()
    assert {:ok, second} = PowlPlatform.Semantics.bundle()
    assert first.files == second.files
    assert Map.has_key?(first.files, "ontology.ttl")
    assert Map.has_key?(first.files, "shapes/operational-profile.ttl")
    assert Map.has_key?(first.files, "r2rml/mapping.ttl")

    ontology = File.read!(Path.expand("../../ontology/ggen-runtime-capabilities.ttl", __DIR__))

    for iri <- [
          "https://powl.dev/ontology/ggen-runtime#ProcessModel",
          "https://powl.dev/ontology/ggen-runtime#WorkflowRun",
          "https://powl.dev/ontology/ggen-runtime#Receipt",
          "https://powl.dev/ontology/ggen-runtime#Intent"
        ] do
      assert ontology =~ iri
    end
  end
end
