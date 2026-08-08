(define (domain mfw-pypi-smoke)
  (:requirements :strips)
  (:predicates (ready) (done))
  (:action finish
    :parameters ()
    :precondition (ready)
    :effect (and (done) (not (ready))))
)
