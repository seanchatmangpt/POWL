defmodule PowlPlatform.PythonExecutor do
  @moduledoc """
  Exact-process bridge to `python -m powl.paas`.

  The bridge is deliberately REPLAY_ONLY. It can execute the real POWL scheduler
  against supplied receipts, but it cannot create fresh external consequences.
  A production DO adapter must remain behind POWL's `ReceiptActuator` contract.
  """

  @behaviour PowlPlatform.Executor

  @impl true
  def run(request) when is_map(request) do
    python = System.get_env("POWL_PYTHON", "python3")
    root = System.get_env("POWL_REPO_ROOT", Path.expand("../..", __DIR__))
    path = Path.join(System.tmp_dir!(), "powl-paas-#{System.unique_integer([:positive, :monotonic])}.json")

    with {:ok, encoded} <- Jason.encode(request),
         :ok <- File.write(path, encoded) do
      try do
        case System.cmd(python, ["-m", "powl.paas", "--request", path],
               cd: root,
               stderr_to_stdout: true
             ) do
          {output, 0} -> decode(output)
          {output, status} -> {:error, {:python_bridge_exit, status, decode_error(output)}}
        end
      after
        File.rm(path)
      end
    end
  end

  defp decode(output) do
    case Jason.decode(output) do
      {:ok, %{"protocol" => "powl-paas/1"} = result} -> {:ok, result}
      {:ok, other} -> {:error, {:invalid_protocol, other}}
      {:error, error} -> {:error, {:invalid_json, error, output}}
    end
  end

  defp decode_error(output) do
    case Jason.decode(output) do
      {:ok, result} -> result
      {:error, _} -> output
    end
  end
end
