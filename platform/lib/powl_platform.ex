defmodule PowlPlatform do
  @moduledoc """
  Ash/AshR2RML/Reactor control plane around the canonical Python POWL runtime.

  Reactor constructs and verifies execution intents. It never reimplements POWL
  partial-order or choice semantics and never receives ambient authority to
  perform business side effects. Fresh DO remains behind POWL's receipted
  actuator boundary.
  """

  @spec run(map(), keyword()) :: {:ok, map()} | {:error, term()}
  def run(request, opts \\ []) when is_map(request) do
    executor = Keyword.get(opts, :executor, PowlPlatform.PythonExecutor)
    Reactor.run(PowlPlatform.RunReactor, %{request: request, executor: executor})
  end
end

defmodule PowlPlatform.Executor do
  @moduledoc "Execution boundary used by the platform Reactor."

  @callback run(map()) :: {:ok, map()} | {:error, term()}
end

defmodule PowlPlatform.Repo do
  @moduledoc "Production AshPostgres repository. The repo is started by the deployment, not semantic compilation."

  use Ecto.Repo,
    otp_app: :powl_platform,
    adapter: Ecto.Adapters.Postgres
end

defmodule PowlPlatform.Domain do
  @moduledoc "POWL PaaS Ash domain."
  use Ash.Domain, validate_config_inclusion?: false

  resources do
    resource PowlPlatform.ProcessModel
    resource PowlPlatform.WorkflowRun
    resource PowlPlatform.Receipt
    resource PowlPlatform.Intent
  end
end

defmodule PowlPlatform.ProcessModel do
  @moduledoc "Admitted POWL model catalog resource."

  use Ash.Resource,
    domain: PowlPlatform.Domain,
    data_layer: AshPostgres.DataLayer,
    extensions: [AshR2RML]

  postgres do
    table "powl_process_models"
    repo PowlPlatform.Repo
  end

  r2rml do
    class_iri "https://powl.dev/ontology/ggen-runtime#ProcessModel"
    subject_template "https://powl.dev/id/model/{id}"
    table_name "powl_process_models"

    attribute_mappings(
      workflow_id: "http://purl.org/dc/terms/identifier",
      name: "http://purl.org/dc/terms/title",
      model_digest: "https://powl.dev/ontology/ggen-runtime#modelDigest",
      standing: "https://powl.dev/ontology/ggen-runtime#standing",
      organization_iri: "https://powl.dev/ontology/ggen-runtime#organizationIri"
    )
  end

  attributes do
    uuid_primary_key :id
    attribute :workflow_id, :string, allow_nil?: false, public?: true
    attribute :name, :string, allow_nil?: false, public?: true
    attribute :model_json, :map, allow_nil?: false, public?: true
    attribute :model_digest, :string, public?: true
    attribute :standing, :string, allow_nil?: false, default: "UNKNOWN", public?: true
    attribute :organization_iri, :string, public?: true
    create_timestamp :inserted_at
    update_timestamp :updated_at
  end

  identities do
    identity :unique_workflow_id, [:workflow_id]
  end

  actions do
    defaults [:read, :destroy]

    create :create do
      primary? true
      accept [:workflow_id, :name, :model_json, :organization_iri]
    end

    update :record_admission do
      accept [:model_digest, :standing]
    end
  end
end

defmodule PowlPlatform.WorkflowRun do
  @moduledoc "Run binding and terminal standing for an admitted POWL subject."

  use Ash.Resource,
    domain: PowlPlatform.Domain,
    data_layer: AshPostgres.DataLayer,
    extensions: [AshR2RML]

  postgres do
    table "powl_workflow_runs"
    repo PowlPlatform.Repo
  end

  r2rml do
    class_iri "https://powl.dev/ontology/ggen-runtime#WorkflowRun"
    subject_template "https://powl.dev/id/run/{id}"
    table_name "powl_workflow_runs"

    attribute_mappings(
      workflow_id: "http://purl.org/dc/terms/identifier",
      model_digest: "https://powl.dev/ontology/ggen-runtime#modelDigest",
      standing: "https://powl.dev/ontology/ggen-runtime#standing",
      receipt_digest: "https://powl.dev/ontology/ggen-runtime#receiptDigest",
      execution_mode: "https://powl.dev/ontology/ggen-runtime#executionMode",
      policy_iri: "https://powl.dev/ontology/ggen-runtime#policyIri"
    )
  end

  attributes do
    uuid_primary_key :id
    attribute :workflow_id, :string, allow_nil?: false, public?: true
    attribute :process_model_id, :uuid, allow_nil?: false, public?: true
    attribute :model_digest, :string, allow_nil?: false, public?: true
    attribute :standing, :string, allow_nil?: false, default: "UNKNOWN", public?: true
    attribute :receipt_digest, :string, public?: true
    attribute :execution_mode, :string, allow_nil?: false, default: "REPLAY_ONLY", public?: true
    attribute :policy_iri, :string, public?: true
    attribute :replayed, :boolean, allow_nil?: false, default: false, public?: true
    create_timestamp :inserted_at
    update_timestamp :updated_at
  end

  actions do
    defaults [:read]

    create :create do
      primary? true
      accept [:id, :workflow_id, :process_model_id, :model_digest, :policy_iri]
    end

    update :record_receipt do
      accept [:standing, :receipt_digest, :replayed]
    end
  end
end

defmodule PowlPlatform.Receipt do
  @moduledoc "Receipted evidence bound to a POWL run/step."

  use Ash.Resource,
    domain: PowlPlatform.Domain,
    data_layer: AshPostgres.DataLayer,
    extensions: [AshR2RML]

  postgres do
    table "powl_receipts"
    repo PowlPlatform.Repo
  end

  r2rml do
    class_iri "https://powl.dev/ontology/ggen-runtime#Receipt"
    subject_template "https://powl.dev/id/receipt/{id}"
    table_name "powl_receipts"

    attribute_mappings(
      receipt_id: "http://purl.org/dc/terms/identifier",
      run_id: "https://powl.dev/ontology/ggen-runtime#runId",
      step_id: "https://powl.dev/ontology/ggen-runtime#stepId",
      kind: "https://powl.dev/ontology/ggen-runtime#stepKind",
      standing: "https://powl.dev/ontology/ggen-runtime#standing",
      consequence_digest: "https://powl.dev/ontology/ggen-runtime#consequenceDigest"
    )
  end

  attributes do
    uuid_primary_key :id
    attribute :receipt_id, :string, allow_nil?: false, public?: true
    attribute :run_id, :uuid, allow_nil?: false, public?: true
    attribute :step_id, :string, public?: true
    attribute :kind, :string, allow_nil?: false, public?: true
    attribute :standing, :string, allow_nil?: false, public?: true
    attribute :consequence_digest, :string, public?: true
    attribute :payload, :map, public?: false
    create_timestamp :inserted_at
  end

  identities do
    identity :unique_receipt_id, [:receipt_id]
  end

  actions do
    defaults [:read]

    create :record do
      primary? true
      accept [:receipt_id, :run_id, :step_id, :kind, :standing, :consequence_digest, :payload]
    end
  end
end

defmodule PowlPlatform.Intent do
  @moduledoc "Non-actuating execution intent. Hooks may manufacture this resource but cannot DO."

  use Ash.Resource,
    domain: PowlPlatform.Domain,
    data_layer: AshPostgres.DataLayer,
    extensions: [AshR2RML]

  postgres do
    table "powl_intents"
    repo PowlPlatform.Repo
  end

  r2rml do
    class_iri "https://powl.dev/ontology/ggen-runtime#Intent"
    subject_template "https://powl.dev/id/intent/{id}"
    table_name "powl_intents"

    attribute_mappings(
      run_id: "https://powl.dev/ontology/ggen-runtime#runId",
      kind: "https://powl.dev/ontology/ggen-runtime#intentKind",
      status: "https://powl.dev/ontology/ggen-runtime#intentStatus",
      authority: "https://powl.dev/ontology/ggen-runtime#authority"
    )
  end

  attributes do
    uuid_primary_key :id
    attribute :run_id, :uuid, allow_nil?: false, public?: true
    attribute :kind, :string, allow_nil?: false, public?: true
    attribute :payload, :map, allow_nil?: false, public?: false
    attribute :status, :string, allow_nil?: false, default: "PENDING", public?: true
    attribute :authority, :string, allow_nil?: false, default: "CONSTRUCT_ONLY", public?: true
    create_timestamp :inserted_at
    update_timestamp :updated_at
  end

  actions do
    defaults [:read]

    create :create do
      primary? true
      accept [:run_id, :kind, :payload]
    end

    update :mark_status do
      accept [:status]
    end
  end
end

defmodule PowlPlatform.Semantics do
  @moduledoc "Build-time AshR2RML semantic projection boundary for ggen/cloud manufacture."

  @resources [
    PowlPlatform.ProcessModel,
    PowlPlatform.WorkflowRun,
    PowlPlatform.Receipt,
    PowlPlatform.Intent
  ]

  @spec resources() :: [module()]
  def resources, do: @resources

  @spec bundle() :: {:ok, map()} | {:error, term()}
  def bundle do
    AshR2RML.Ggen.compile_ash_ttl_bundle(@resources)
  end
end
