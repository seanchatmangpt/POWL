#![forbid(unsafe_code)]

pub mod wasm4pm_cognition {
    #[repr(C)]
    #[derive(Copy, Clone, Debug, Eq, PartialEq)]
    pub struct Rule {
        pub premise_mask: u32,
        pub conclusion_add_mask: u32,
        pub conclusion_del_mask: u32,
    }

    impl Rule {
        pub const fn empty() -> Self {
            Self { premise_mask: 0, conclusion_add_mask: 0, conclusion_del_mask: 0 }
        }
    }
}

#[repr(C)]
#[derive(Copy, Clone, Debug)]
pub struct ToolCandidate {
    pub tool_id: u8,
    pub semantic_fit: u8,
    pub evidence_fit: u8,
    pub authority_fit: u8,
    pub timing_fit: u8,
    pub downstream_fit: u8,
    pub reliability: u8,
    pub cost_fit: u8,
    pub mass: u8,
    pub cognition_rule: wasm4pm_cognition::Rule,
}

#[repr(C)]
#[derive(Copy, Clone, Debug)]
pub struct AutoSelectInput8 {
    pub request_id: u32,
    pub eligible_mask: u8,
    pub ready_mask: u8,
    pub policy_valid: bool,
    pub required_authority: u16,
    pub q_lens: u8,
    pub state_mask: u32,
    pub k_sync: u64,
    pub chaos_delta: u32,
    pub candidates: [ToolCandidate; 8],
}

#[repr(C)]
#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub struct AutoSelectOutcome {
    pub best_id: u8,
    pub found_mask: u32,
}

#[repr(u8)]
#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub enum AutoSelectRefusal {
    UnsupportedDomain = 1,
    NumericRangeExceeded = 2,
    ContractViolation = 3,
    ControlStateUnadmitted = 12,
}

pub type AutoSelectResult = Result<AutoSelectOutcome, AutoSelectRefusal>;

const fn pow7(x: u64) -> u64 {
    let x2 = x.wrapping_mul(x);
    let x4 = x2.wrapping_mul(x2);
    x4.wrapping_mul(x2).wrapping_mul(x)
}

pub const fn calculate_canonical_mass(c: &ToolCandidate) -> u8 {
    let mut prod = 1u64;
    prod = prod.wrapping_mul(c.semantic_fit as u64);
    prod = prod.wrapping_mul(c.evidence_fit as u64);
    prod = prod.wrapping_mul(c.authority_fit as u64);
    prod = prod.wrapping_mul(c.timing_fit as u64);
    prod = prod.wrapping_mul(c.downstream_fit as u64);
    prod = prod.wrapping_mul(c.reliability as u64);
    prod = prod.wrapping_mul(c.cost_fit as u64);
    let mut res = 0u64;
    let mut bit = 128u64;
    while bit != 0 {
        let next = res | bit;
        if pow7(next) <= prod { res = next; }
        bit >>= 1;
    }
    res as u8
}

pub const fn select(input: &AutoSelectInput8) -> AutoSelectResult {
    if input.q_lens == 0 || input.q_lens > 4 {
        return Err(AutoSelectRefusal::UnsupportedDomain);
    }
    if !input.policy_valid {
        return Err(AutoSelectRefusal::ControlStateUnadmitted);
    }
    let admissible = input.eligible_mask & input.ready_mask;
    let mut best_score = 0u8;
    let mut best_id = 0u8;
    let mut found = false;
    let mut i = 0usize;
    while i < 8 {
        let c = input.candidates[i];
        if c.tool_id >= 8 { return Err(AutoSelectRefusal::NumericRangeExceeded); }
        let bit = 1u8 << (c.tool_id & 7);
        let premise_ok = (input.state_mask & c.cognition_rule.premise_mask) == c.cognition_rule.premise_mask;
        if (admissible & bit) != 0 && premise_ok {
            let score = calculate_canonical_mass(&c);
            if score > best_score {
                best_score = score;
                best_id = c.tool_id;
                found = true;
            }
        }
        i += 1;
    }
    if found {
        Ok(AutoSelectOutcome { best_id, found_mask: u32::MAX })
    } else {
        Err(AutoSelectRefusal::ContractViolation)
    }
}
