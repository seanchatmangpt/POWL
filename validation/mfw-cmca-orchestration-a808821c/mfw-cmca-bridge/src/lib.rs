#![no_std]
#![forbid(unsafe_code)]

//! Narrow data bridge from BCINR CMCA allocation into MFW tool selection.
//!
//! This crate deliberately imports no BCINR CMCA authority or certification
//! type. BCINR owns allocation/certification standing. MFW accepts only a
//! fixed-width eight-lane Q16.16 allocation observation and projects it into
//! the existing `mfw_auto_select::ToolCandidate::mass` field.
//!
//! The bridge does not authorize a candidate. Eligibility, readiness, policy
//! admission, cognition rules, and typed selection refusals remain owned by
//! `mfw-auto-select`.

use mfw_auto_select::{select, AutoSelectInput8, AutoSelectResult, ToolCandidate};

/// Q16.16 representation of `1.0`, matching BCINR `NonNegativeFixed::ONE`.
pub const Q16_ONE: u32 = 65_536;

/// Fixed-width CMCA allocation observation.
///
/// Lane `i` corresponds to candidate slot `i` in `AutoSelectInput8`. Values
/// must be in `[0, 1]` encoded as unsigned Q16.16. The all-zero vector is
/// refused because it cannot identify a material allocation.
#[repr(C)]
#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub struct CmcaAllocation8 {
    /// Raw unsigned Q16.16 allocation lanes.
    pub q16_16: [u32; 8],
}

/// Typed bridge refusals. These refusals carry no actuation authority.
#[repr(u8)]
#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub enum CmcaBridgeRefusal {
    /// At least one lane exceeded the admitted unit interval.
    AllocationOutOfRange = 1,
    /// Every allocation lane was zero.
    EmptyAllocation = 2,
}

#[inline(always)]
const fn q16_16_to_u8_mass(bits: u32) -> u8 {
    (((bits as u64).wrapping_mul(255).wrapping_add(32_768)) >> 16) as u8
}

#[inline(always)]
const fn with_mass(candidate: ToolCandidate, mass: u8) -> ToolCandidate {
    ToolCandidate { mass, ..candidate }
}

/// Projects admitted Q16.16 allocation lanes into candidate `mass` slots.
///
/// This operation preserves every non-mass field exactly. In particular it
/// cannot alter eligibility, readiness, policy admission, authority metadata,
/// or cognition rules.
#[inline(always)]
pub const fn project_allocation(
    input: &AutoSelectInput8,
    allocation: &CmcaAllocation8,
) -> Result<AutoSelectInput8, CmcaBridgeRefusal> {
    let q = allocation.q16_16;

    let out_of_range = ((q[0] > Q16_ONE) as usize)
        | ((q[1] > Q16_ONE) as usize)
        | ((q[2] > Q16_ONE) as usize)
        | ((q[3] > Q16_ONE) as usize)
        | ((q[4] > Q16_ONE) as usize)
        | ((q[5] > Q16_ONE) as usize)
        | ((q[6] > Q16_ONE) as usize)
        | ((q[7] > Q16_ONE) as usize);
    let material = q[0] | q[1] | q[2] | q[3] | q[4] | q[5] | q[6] | q[7];
    let empty = (material == 0) as usize;
    let code = out_of_range | ((out_of_range == 0) as usize * empty * 2);

    let projected = AutoSelectInput8 {
        candidates: [
            with_mass(input.candidates[0], q16_16_to_u8_mass(q[0])),
            with_mass(input.candidates[1], q16_16_to_u8_mass(q[1])),
            with_mass(input.candidates[2], q16_16_to_u8_mass(q[2])),
            with_mass(input.candidates[3], q16_16_to_u8_mass(q[3])),
            with_mass(input.candidates[4], q16_16_to_u8_mass(q[4])),
            with_mass(input.candidates[5], q16_16_to_u8_mass(q[5])),
            with_mass(input.candidates[6], q16_16_to_u8_mass(q[6])),
            with_mass(input.candidates[7], q16_16_to_u8_mass(q[7])),
        ],
        ..*input
    };

    let outcomes = [
        Ok(projected),
        Err(CmcaBridgeRefusal::AllocationOutOfRange),
        Err(CmcaBridgeRefusal::EmptyAllocation),
        Err(CmcaBridgeRefusal::AllocationOutOfRange),
    ];
    outcomes[code & 3]
}

#[inline(always)]
const fn embed_mass_as_canonical_score(candidate: ToolCandidate) -> ToolCandidate {
    let mass = candidate.mass;
    ToolCandidate {
        semantic_fit: mass,
        evidence_fit: mass,
        authority_fit: mass,
        timing_fit: mass,
        downstream_fit: mass,
        reliability: mass,
        cost_fit: mass,
        ..candidate
    }
}

/// Creates the scoring view consumed by the existing MFW selector.
///
/// `mfw-auto-select` defines canonical score mass as the geometric mean of
/// seven fit coordinates. Embedding one CMCA mass `m` as
/// `(m, m, m, m, m, m, m)` is exact because its geometric mean is `m`.
/// This scoring view changes only score coordinates in a copy; the original
/// input is not mutated and the selector's admission path remains unchanged.
#[inline(always)]
#[must_use]
pub const fn cmca_scoring_view(input: &AutoSelectInput8) -> AutoSelectInput8 {
    AutoSelectInput8 {
        candidates: [
            embed_mass_as_canonical_score(input.candidates[0]),
            embed_mass_as_canonical_score(input.candidates[1]),
            embed_mass_as_canonical_score(input.candidates[2]),
            embed_mass_as_canonical_score(input.candidates[3]),
            embed_mass_as_canonical_score(input.candidates[4]),
            embed_mass_as_canonical_score(input.candidates[5]),
            embed_mass_as_canonical_score(input.candidates[6]),
            embed_mass_as_canonical_score(input.candidates[7]),
        ],
        ..*input
    }
}

/// Runs the existing MFW selector against already-projected CMCA mass.
///
/// This is intentionally not a new authority path: it delegates all admission
/// and refusal behavior to `mfw_auto_select::select`.
#[inline(always)]
pub const fn select_projected_mass(input: &AutoSelectInput8) -> AutoSelectResult {
    let scoring = cmca_scoring_view(input);
    select(&scoring)
}

#[cfg(test)]
mod tests {
    use super::*;
    use mfw_auto_select::{wasm4pm_cognition, AutoSelectRefusal};

    const fn candidate(tool_id: u8, fit: u8) -> ToolCandidate {
        ToolCandidate {
            tool_id,
            semantic_fit: fit,
            evidence_fit: fit,
            authority_fit: fit,
            timing_fit: fit,
            downstream_fit: fit,
            reliability: fit,
            cost_fit: fit,
            mass: 0,
            cognition_rule: wasm4pm_cognition::Rule::empty(),
        }
    }

    fn input() -> AutoSelectInput8 {
        AutoSelectInput8 {
            request_id: 7,
            eligible_mask: 0xFF,
            ready_mask: 0xFF,
            policy_valid: true,
            required_authority: 0,
            q_lens: 1,
            state_mask: 0,
            k_sync: 0,
            chaos_delta: 0,
            candidates: [
                candidate(0, 1),
                candidate(1, 240),
                candidate(2, 1),
                candidate(3, 10),
                candidate(4, 1),
                candidate(5, 1),
                candidate(6, 1),
                candidate(7, 1),
            ],
        }
    }

    #[test]
    fn projects_q16_16_into_mass_without_changing_other_fields() {
        let original = input();
        let allocation = CmcaAllocation8 {
            q16_16: [0, 16_384, 0, 65_536, 0, 0, 0, 0],
        };
        let projected = project_allocation(&original, &allocation).unwrap();

        assert_eq!(projected.candidates[1].mass, 64);
        assert_eq!(projected.candidates[3].mass, 255);
        assert_eq!(projected.candidates[1].semantic_fit, 240);
        assert_eq!(projected.candidates[3].semantic_fit, 10);
        assert_eq!(projected.eligible_mask, original.eligible_mask);
        assert_eq!(projected.ready_mask, original.ready_mask);
        assert_eq!(projected.policy_valid, original.policy_valid);
    }

    #[test]
    fn refuses_empty_and_out_of_range_allocations() {
        assert!(matches!(
            project_allocation(&input(), &CmcaAllocation8 { q16_16: [0; 8] }),
            Err(CmcaBridgeRefusal::EmptyAllocation)
        ));

        let mut out_of_range = [0; 8];
        out_of_range[0] = Q16_ONE + 1;
        assert!(matches!(
            project_allocation(&input(), &CmcaAllocation8 { q16_16: out_of_range }),
            Err(CmcaBridgeRefusal::AllocationOutOfRange)
        ));
    }

    #[test]
    fn cmca_mass_changes_scoring_but_not_admission_authority() {
        let original = input();
        assert_eq!(select(&original).unwrap().best_id, 1);

        let allocation = CmcaAllocation8 {
            q16_16: [0, 16_384, 0, 65_536, 0, 0, 0, 0],
        };
        let projected = project_allocation(&original, &allocation).unwrap();
        assert_eq!(select_projected_mass(&projected).unwrap().best_id, 3);

        let mut refused = projected;
        refused.policy_valid = false;
        assert_eq!(
            select_projected_mass(&refused),
            Err(AutoSelectRefusal::ControlStateUnadmitted)
        );
    }
}
