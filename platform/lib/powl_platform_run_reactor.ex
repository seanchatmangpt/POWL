defmodule PowlPlatform.RunReactor do
  @moduledoc """
  Platform orchestration around the POWL runtime.

  This Reactor performs SELECT/CONSTRUCT/VERIFY only. The executor boundary may
  invoke POWL, but Reactor does not interpret POWL graph semantics and never
  directly actuates an external business consequence.
  """

  use Reactor

  @standings ~w(UNKNOWN PARTIAL_ALIVE ALIVE BLOCKED BUILD_BROKEN UNSUPPORTED REFUSED)

  input :request
  input :executor

  step :admit_request do
    argument :request, input(:request)

    run fn %{request: request}, _ctx ->
      required = [:run_id, :workflow_id, :model_document]
      missing = Enum.reject(required, &present?(request, &1))

      cond do
        missing != [] ->
          {:error, {:REFUSED, :ADMISSION, "missing required fields: #{Enum.join(missing, ", ")}"}}

        execution_mode(request) != "REPLAY_ONLY" ->
          {:error,
           {:REFUSED, :UNSUPPORTED_EXECUTION_MODE,
            "platform bridge is REPLAY_ONLY; fresh DO must use an authorized receipted actuator adapter"}}

        true ->
          {:ok, request}
      end
    end
  end

  step :construct_intent do
    argument :request, result(:admit_request)

    run fn %{request: request}, _ctx ->
      {:ok,
       %{
         kind: "RUN_POWL",
         authority: "CONSTRUCT_ONLY",
         execution_mode: "REPLAY_ONLY",
         request: request
       }}
    end
  end

  step :execute_powl do
    argument :intent, result(:construct_intent)
    argument :executor, input(:executor)

    run fn %{intent: intent, executor: executor}, _ctx ->
      executor.run(intent.request)
    end
  end

  step :verify_receipt do
    argument :result, result(:execute_powl)

    run fn %{result: result}, _ctx ->
      with {:ok, receipt} <- fetch_map(result, "receipt"),
           {:ok, standing} <- fetch_string(receipt, "standing"),
           true <- standing in @standings,
           {:ok, _run_id} <- fetch_string(receipt, "run_id"),
           {:ok, _workflow_id} <- fetch_string(receipt, "workflow_id"),
           {:ok, digest} <- fetch_string(receipt, "receipt_digest"),
           true <- byte_size(digest) > 0 do
        {:ok, result}
      else
        false -> {:error, {:BUILD_BROKEN, :INVALID_RECEIPT, "receipt failed standing/digest validation"}}
        {:error, detail} -> {:error, {:BUILD_BROKEN, :INVALID_RECEIPT, detail}}
      end
    end
  end

  collect :platform_result do
    argument :intent, result(:construct_intent)
    argument :runtime, result(:verify_receipt)

    transform fn %{intent: intent, runtime: runtime} ->
      %{
        intent: Map.drop(intent, [:request]),
        runtime: runtime,
        authority: "BRCE_BOUNDARY",
        standing: get_in(runtime, ["receipt", "standing"]) || "UNKNOWN"
      }
    end
  end

  return :platform_result

  defp present?(map, key) do
    value = Map.get(map, key, Map.get(map, Atom.to_string(key)))
    not is_nil(value) and value != ""
  end

  defp execution_mode(map) do
    Map.get(map, :execution_mode, Map.get(map, "execution_mode", "REPLAY_ONLY"))
  end

  defp fetch_map(map, key) do
    case Map.get(map, key) do
      value when is_map(value) -> {:ok, value}
      _ -> {:error, "missing map field #{key}"}
    end
  end

  defp fetch_string(map, key) do
    value = Map.get(map, key)
    if is_binary(value) and value != "", do: {:ok, value}, else: {:error, "missing string field #{key}"}
  end
end
