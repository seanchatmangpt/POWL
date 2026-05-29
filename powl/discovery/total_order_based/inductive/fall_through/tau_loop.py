from collections import Counter
from typing import Any, Dict, Optional

from pm4py.algo.discovery.inductive.fall_through.tau_loop import TauLoopUVCL
from pm4py.util.compression import util as comut
from pm4py.util.compression.dtypes import UVCL

from powl.discovery.total_order_based.inductive.dtypes.partial_order import IMDataStructurePOT, split_project_pot_by_start_boundaries
from powl.discovery.total_order_based.inductive.fall_through.strict_tau_loop import (
    POWLStrictTauLoopPOT,
    POWLStrictTauLoopUVCL,
)


class POWLTauLoopUVCL(POWLStrictTauLoopUVCL, TauLoopUVCL):
    @classmethod
    def _get_projected_log(
        cls, log: UVCL, parameters: Optional[Dict[str, Any]] = None
    ) -> UVCL:
        start_activities = comut.get_start_activities(log)
        proj = Counter()
        for t in log:
            x = 0
            for i in range(1, len(t)):
                if t[i] in start_activities:
                    proj.update({t[x:i]: log[t]})
                    x = i
            proj.update({t[x : len(t)]: log[t]})
        return proj

class POWLTauLoopPOT(POWLStrictTauLoopPOT):
    @classmethod
    def _get_projected_log(
        cls, im_data_struct: IMDataStructurePOT, parameters: Optional[Dict[str, Any]] = None
    ) -> IMDataStructurePOT:
        log = im_data_struct.data_structure
        start_acts=set(im_data_struct.dfg.start_activities)
        end_acts=set(im_data_struct.dfg.end_activities)
        proj_data_struct = split_project_pot_by_start_boundaries(log,"any_to_start",start_acts,end_acts)
        return proj_data_struct