from collections import Counter
from multiprocessing import Manager, Pool
from typing import Any, Dict, List, Optional, Tuple

from pm4py.algo.discovery.inductive.dtypes.im_ds import IMDataStructureUVCL
from pm4py.algo.discovery.inductive.fall_through.strict_tau_loop import (
    FallThrough,
    StrictTauLoopUVCL,
)

from powl.discovery.total_order_based.inductive.dtypes.partial_order import IMDataStructurePOT, PartialOrderTrace, split_project_pot_by_start_boundaries
from powl.discovery.total_order_based.inductive.modeling import LoopSpec


class POWLStrictTauLoopUVCL(StrictTauLoopUVCL):
    @classmethod
    def apply(
        cls,
        obj: IMDataStructureUVCL,
        pool: Pool = None,
        manager: Manager = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Optional[Tuple[LoopSpec, List[IMDataStructureUVCL]]]:
        log = obj.data_structure
        proj = cls._get_projected_log(log)
        if sum(proj.values()) > sum(log.values()):
            return LoopSpec(2), [
                IMDataStructureUVCL(proj),
                IMDataStructureUVCL(Counter()),
            ]

class POWLStrictTauLoopPOT(FallThrough[IMDataStructurePOT]):
    @classmethod
    def _get_projected_log(
        cls, im_data_struct: IMDataStructurePOT, parameters: Optional[Dict[str, Any]] = None
    ) -> IMDataStructurePOT:
        log = im_data_struct.data_structure
        start_acts=set(im_data_struct.dfg.start_activities)
        end_acts=set(im_data_struct.dfg.end_activities)
        proj_data_structure = split_project_pot_by_start_boundaries(log,"end_to_start",start_acts,end_acts)
        return proj_data_structure

    @classmethod
    def holds(
        cls,
        obj: IMDataStructurePOT,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return sum(cls._get_projected_log(obj).data_structure.values()) > sum(obj.data_structure.values())

    @classmethod
    def apply(
        cls,
        obj: IMDataStructurePOT,
        pool=None,
        manager=None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Optional[Tuple[LoopSpec, List[IMDataStructurePOT]]]:
        proj_data_struct = cls._get_projected_log(obj)
        if sum(proj_data_struct.data_structure.values()) > sum(obj.data_structure.values()):
            return LoopSpec(2), [proj_data_struct,IMDataStructurePOT(Counter())]
            
