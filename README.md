# 🔍 POWL Miner
**Process Mining with the Partially Ordered Workflow Language**

The POWL Miner allows you to perform **process discovery from event logs**, leveraging the **Partially Ordered Workflow Language (POWL) 2.0**. The generated POWL 2.0 models can be viewed and exported as BPMNs or Petri nets (PNML). For more details on POWL 2.0, please refer to the paper: [**Unlocking Non-Block-Structured Decisions: Inductive Mining with Choice Graphs**](https://arxiv.org/abs/2505.07052).


## 🚀 Launching as a Streamlit App

You have two options for running the POWL Miner as a Streamlit App:

### ☁️ On the Cloud
Access the hosted version directly:
[**https://powl-miner.streamlit.app/**](https://powl-miner.streamlit.app/)

### 💻 Locally
To run the Streamlit application on your own machine:

  1. Clone this repository.
  2. Install the required dependencies ('requirements.txt') and packages ('packages.txt').
  3. Run:
     ```bash
     streamlit run app.py
     ```
#### <img src="https://raw.githubusercontent.com/mustay/dashboard-icons/master/png/docker.png" alt="Docker icon" width="20" height="20"> Docker:

Alternatively, you can install it using the provided Docker image:

1. Pull the Docker image:
     ```bash
     docker pull ghcr.io/humam-kourani/powl:latest
     ```
2. Run the app:
     ```bash
     docker run -p 8501:8501 powl
     ```




## 🐍 Installing as a Python Library

You can also install the POWL Miner as a Python library to integrate its functionalities into your own scripts.

1. Install the required packages ('packages.txt').
2. Install the library via pip:
    ```bash
    pip install powl
    ```

**👉 Usage Example:**
     Check the `examples/` directory of this repository.

## ⚙️ Receipted workflow runtime

`powl.runtime` executes admitted `TaggedPOWL` models without giving model structure ambient authority to perform effects. The runtime keeps business selection separate from actuation and requires every observable activity to cross a receipt-producing actuator boundary.

```python
from powl.objects.tagged_powl.activity import Activity
from powl.runtime import ActuationReceipt, Standing, WorkflowRunner

class Payments:
    async def actuate(self, command):
        # Use command.idempotency_key at the external system boundary.
        result = await charge(command.inputs)
        return ActuationReceipt(
            receipt_id=result.receipt_id,
            standing=Standing.ALIVE,
            output={"payment_id": result.payment_id},
        )

model = Activity(label="Charge card")
receipt = await WorkflowRunner(Payments()).run(
    model,
    run_id="order-7",
    workflow_id="checkout-v3",
)
```

For composite `PartialOrder` and `ChoiceGraph` models, each direct child must carry a stable `attributes["execution_id"]`. This makes model identity, step identity, replay, and receipts independent of Python object addresses or set iteration order.

Runtime guarantees:

- bounded asynchronous fan-out for partial orders while preserving predecessor barriers;
- explicit, persisted selection for non-forced choice-graph branches and variable frequency;
- stable run/model/step identity and idempotency keys;
- zero unreceipted retry: actuator exceptions and timeouts block the run because external consequence is unknown;
- retries only after an actuator returns a persisted `BLOCKED` receipt marked `retryable=True`;
- run and step replay through a `RunStore`, including lease-aware step claims for distributed workers;
- expired claims are sealed `BLOCKED` and fence stale workers instead of re-actuating unknown consequences;
- typed `REFUSED`, `BLOCKED`, `BUILD_BROKEN`, `UNSUPPORTED`, and `ALIVE` standing.

`InMemoryRunStore` is the single-process reference implementation. Multi-worker deployments should implement the `RunStore` protocol over a transactional database or strongly consistent key/value store so `bind_run`, `claim_step`, and `save_step` retain their atomic semantics across processes.


### Third-Party Licenses
This project bundles [bpmn-auto-layout](https://www.npmjs.com/package/bpmn-auto-layout),
which is licensed under the MIT License. See `THIRD_PARTY_LICENSES.txt` for details.
