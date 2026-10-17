# Stake and debt updates

Even-money binary outcome. Shared cash \(C\). Lineages \(L\) (long) and \(S\) (short).

Branching does not create positive expectancy when \(p \le 0.5\), and finite capital can still ruin the path. The split changes how debt is carried, not the edge.

A trace row is one settled step. `long_stake` and `short_stake` are the book that just settled. Debt is the debt after that settlement and after any collapse. The next book is the stake pair on the following row. `reset` is 1 when either lineage collapsed on the step.

## Settlement

Draw \(U_t \in \{\text{up}, \text{down}\}\) with \(P(\text{up}) = p\). Up wins the long stake and loses the short stake.

If up, and each stake was actually open:

- \(C \leftarrow C + \text{stake}_L - \text{stake}_S\)
- \(\text{debt}_L \leftarrow \max(0,\ \text{debt}_L - \text{stake}_L)\)
- \(\text{debt}_S \leftarrow \text{debt}_S + \text{stake}_S\)
- streak\(_L \leftarrow 0\), and streak\(_S\) increases by 1

Down swaps \(L\) and \(S\). A lineage with a zero stake is left unchanged. Surplus above a cleared debt stays in shared cash because the full winning stake was added to \(C\) before debt was floored at 0.

## Recovery target

A lineage with debt \(D\) is trying to get back to a fresh cycle that nets one base unit \(b\):

\[
S = D + b
\]

Along an unsplit losing run this is the same number as a pure double. After a loss of the previous stake \(s\),

\[
D \leftarrow D + s, \qquad S = D + b = 2s
\]

when the run so far was itself a sequence of doubles from base. Before the branch trigger, the next continue stake is

\[
\min(2s,\ S)
\]

so the book escalates like a martingale and never bets more than the amount that would clear the debt and net one base.

## Bifurcation

Split when the lineage's loss streak is at least \(k\), or its debt is at least \(\tau\) (default \(\tau = 8b\), stored as an absolute level).

\[
S_{\text{continue}} = \alpha S, \qquad S_{\text{counter}} = (1 - \alpha) S
\]

with \(\alpha \in [0.5, 1]\). The counter stake opens the other lineage, or adds to the stake that lineage already proposed.

Depth counts generations of the two lineages, not every added unit of stake. If the opposite lineage already has debt, the counter stake is added and its depth stays. If it is clear, the counter stake opens it and its depth becomes the parent's depth plus 1. If that child depth would exceed \(d_{\max}\), do not open it. The continue side then bets \(\min(S, b)\) only.

## Collapse

After settlement, a lineage that had an open stake and now has \(\text{debt} \le 0\) collapses: debt 0, streak 0, depth 0, and `reset` is marked. If every lineage is clear, the next book is the root again (base on the favored side, or \(b/2\) on each side when \(p = 0.5\)). If the other lineage is still in debt, the collapsed lineage reopens at base, plus any counter stake the other side adds.

## Risk cap and cash

Let \(B = r C_0\). A proposed book is placed as-is only when

\[
\text{stake}_L + \text{stake}_S \le B \quad \text{and} \quad \text{stake}_L + \text{stake}_S \le C.
\]

Otherwise escalation freezes. Each positive leg is cut to at most \(b\), favored side first, and a leg that still does not fit is skipped. No stake is partial-filled. The engine refuses a book whose sum exceeds cash or \(B\).

## Ruin

If the next book is empty and \(C < b\), and the horizon is not already over, the path is ruined. `ruin_step` is the 1-based index of the stake that could not be funded. Reaching the horizon stops the path even when the stake after the last bet would not have fit.

## Log-growth floor

Ensemble mean log-growth is \(\mathbb{E}[\ln(W / C_0)]\). A ruined path, or a non-positive terminal, uses \(W = 1\) (one currency unit). Median terminal wealth still uses the cash that was left.
