#![forbid(unsafe_code)]
use mfw_auto_select::{wasm4pm_cognition, AutoSelectInput8, AutoSelectRefusal, ToolCandidate};
use mfw_cmca_bridge::{project_allocation, select_projected_mass, CmcaAllocation8, CmcaBridgeRefusal, Q16_ONE};

fn candidate(tool_id: u8, fit: u8) -> ToolCandidate {
    ToolCandidate { tool_id, semantic_fit: fit, evidence_fit: fit, authority_fit: fit, timing_fit: fit, downstream_fit: fit, reliability: fit, cost_fit: fit, mass: 0, cognition_rule: wasm4pm_cognition::Rule::empty() }
}

fn input() -> AutoSelectInput8 {
    AutoSelectInput8 { request_id: 2691, eligible_mask: 0xff, ready_mask: 0xff, policy_valid: true, required_authority: 0, q_lens: 1, state_mask: 0, k_sync: 0, chaos_delta: 0, candidates: [candidate(0,1), candidate(1,240), candidate(2,1), candidate(3,10), candidate(4,1), candidate(5,1), candidate(6,1), candidate(7,1)] }
}

fn main() {
    let allocation = CmcaAllocation8 { q16_16: [0, 16_384, 0, Q16_ONE, 0, 0, 0, 0] };
    let projected = project_allocation(&input(), &allocation).expect("admitted CMCA observation");
    assert_eq!(projected.candidates[1].mass, 64);
    assert_eq!(projected.candidates[3].mass, 255);
    assert_eq!(select_projected_mass(&projected).expect("selection").best_id, 3);
    assert_eq!(project_allocation(&input(), &CmcaAllocation8 { q16_16: [0;8] }), Err(CmcaBridgeRefusal::EmptyAllocation));
    let mut bad = [0u32;8]; bad[7] = Q16_ONE + 1;
    assert_eq!(project_allocation(&input(), &CmcaAllocation8 { q16_16: bad }), Err(CmcaBridgeRefusal::AllocationOutOfRange));
    let mut policy_refused = projected; policy_refused.policy_valid = false;
    assert_eq!(select_projected_mass(&policy_refused), Err(AutoSelectRefusal::ControlStateUnadmitted));
    println!("subject=mfw@a808821c6636535bc80f59f660b5b35906948c8e bridge_blob=64e2c55b574432525af68637f7b3fe843152f592 selected=3 mass1=64 mass3=255 empty_refused=1 range_refused=1 policy_refused=1 actuation=0");
}
