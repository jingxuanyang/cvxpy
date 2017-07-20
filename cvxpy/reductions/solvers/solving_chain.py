from cvxpy.constraints import ExpCone, PSD, SOC
from cvxpy.error import DCPError, SolverError
from cvxpy.problems.objective import Maximize
from cvxpy.reductions import (Chain, ConeMatrixStuffing, Dcp2Cone,
                              FlipObjective, Qp2SymbolicQp, QpMatrixStuffing)
from cvxpy.reductions.solvers.candidate_qp_solvers import QpSolver
from cvxpy.reductions.solvers import Solver
from cvxpy.reductions.solvers.utilities import (SOLVER_MAP as SLV_MAP,
                                                INSTALLED_SOLVERS,
                                                CONIC_SOLVERS,
                                                QP_SOLVERS)


def construct_solving_chain(problem, solver=None):
    """Build a reduction chain from a problem to an installed solver

    Parameters
    ----------
    problem : Problem
        The problem for which to build a chain.
    solver : string
        The name of the solver with which to terminate the chain. If no solver
        is supplied (i.e., if solver is None), then the targeted solver may be
        any of those that are installed.

    Returns
    -------
    SolvingChain
        A SolvingChain that can be used to solve the problem.

    Raises
    ------
    DCPError
        Raised if the problem is not DCP.
    SolverError
        Raised if no suitable solver exists among the installed solvers.
    """

    if solver is not None:
        if solver not in INSTALLED_SOLVERS:
            raise SolverError("Solver %s is not installed" % solver)
        candidates = [solver]
    else:
        candidates = INSTALLED_SOLVERS

    # Presently, we have but two reduction chains:
    #   (1) Qp2SymbolicQp --> QpMatrixStuffing --> QpSolver,
    #   (2) Dcp2Cone --> ConeMatrixStuffing --> [a ConicSolver]
    # Both of these chains require that the problem is DCP.
    if not problem.is_dcp():
        raise DCPError("Problem does not follow DCP rules.")
    if problem.is_mip():
        candidates = [s for s in candidates if SLV_MAP[s].MIP_CAPABLE]
        if not candidates:
            raise SolverError("Problem is mixed integer, but candidate "
                              "solvers (%s) are not MIP-capable." %
                              candidates)

    # Both reduction chains exclusively accept minimization problems.
    reductions = []
    if type(problem.objective) == Maximize:
        reductions.append(FlipObjective())

    candidate_qp_solvers = [s for s in QP_SOLVERS if s in candidates]
    if candidate_qp_solvers and problem.is_qp():
        solver = sorted(candidate_qp_solvers, key s: QP_SOLVERS.index(s))
        reductions += [Qp2SymbolicQp(),
                       QpMatrixStuffing(),
                       QpSolver(solver.name)]
        return SolvingChain(reductions=reductions)

    candidate_conic_solvers = [s for s in CONIC_SOLVERS if s in candidates]
    if not candidate_conic_solvers:
        raise SolverError("Problem could not be reduced to a QP, and no "
                          "conic solvers exist among candidate solvers "
                          "(%s)." % candidates)
    # Our choice of solver depends upon which atoms are present in the
    # problem. The types of atoms to check for are SOC atoms, PSD atoms,
    # and EXP atoms.
    atoms = problem.atoms()
    cones = []
    # TODO(akshayka): Define SOC_ATOMS somewhere and import it into this file;
    # similarly for PSD_ATOMS and EXP_ATOMS
    if any(type(atom) in SOC_ATOMS for atom in atoms):
        cones.append(SOC)
    if any(type(atom) in EXP_ATOMS for atom in atoms):
        cones.append(ExpCone)
    if any(type(atom) in PSD_ATOMS for atom in atoms):
        cones.append(PSD)

    for solver in sorted(candidate_conic_solvers,
                    key=lambda s: CONIC_SOLVERS.index(s)):
        if all(c in s.SUPPORTED_CONSTRAINTS for c in cones):
            reductions += [Dcp2Cone, ConeMatrixStuffing, SLV_MAP[solver]]
            return SolvingChain(reductions=reductions)
    raise SolverError("Candidate conic solvers (%s) do not support the cones "
                      "output by the problem (%s)." % (candidate_conic_solvers,
                                                        ', '.join(cones)))


class SolvingChain(Chain):
    """TODO(akshayka): Document
    """

    def __init__(self, reductions=[]):
        if not isinstance(self.reductions[-1], Solver):
            raise ValueError("Solving chains must terminate with a Solver.")
        self.problem_reductions = self.reductions[:-1]
        self.solver = self.reductions[-1]

    def solve(problem, warm_start, verbose, solver_opts):
        data, inverse_data = self.apply(problem)
        solution = self.solver.solve_via_data(data, warm_start,
                                              verbose, solver_opts)
        return self.invert(solution, inverse_data)