defmodule PowlPlatform.MixProject do
  use Mix.Project

  @ash_r2rml_ref "067954ad406fd637fd47646bdb10c4580809c79d"

  def project do
    [
      app: :powl_platform,
      version: "26.8.26",
      elixir: "~> 1.17",
      start_permanent: Mix.env() == :prod,
      deps: deps()
    ]
  end

  def application do
    [extra_applications: [:logger, :crypto]]
  end

  defp deps do
    [
      {:ash, "~> 3.32"},
      {:ash_postgres, "~> 2.11"},
      {:ash_r2rml,
       git: "https://github.com/seanchatmangpt/ash_r2rml.git",
       ref: @ash_r2rml_ref},
      {:reactor, "~> 1.0"},
      {:jason, "~> 1.4"}
    ]
  end
end
