"""
neat_brain.py — Pure-Python NEAT (NeuroEvolution of Augmenting Topologies) engine
for the Hill Climb Racing Trainer auto-play feature.

Ported from the JavaScript reference implementation.
No third-party dependencies — stdlib only (math, random, copy).
"""

import math
import random
import copy


# ---------------------------------------------------------------------------
# Global innovation counter
# ---------------------------------------------------------------------------
_next_innovation_no: int = 0


def _new_innovation() -> int:
    global _next_innovation_no
    _next_innovation_no += 1
    return _next_innovation_no


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------
class Node:
    """A neuron in the NEAT network graph.

    Attributes:
        number: Unique node identifier within the genome.
        layer:  Layer index used for topological ordering (0 = input, 1 = output,
                2+ = hidden).
        output_value: Activation value computed during feed-forward.
        output_connections: List of ConnectionGene objects leaving this node.
    """

    def __init__(self, number: int, layer: int = 0) -> None:
        self.number: int = number
        self.layer: int = layer
        self.output_value: float = 0.0
        self.output_connections: list = []  # List[ConnectionGene]

    def engage(self) -> None:
        """Compute sigmoid activation from all enabled incoming connections.

        Sums weight * from_node.output_value for every enabled incoming
        connection, then applies the sigmoid 1/(1+exp(-4.9*total)) and
        stores the result in output_value.

        Note: Input nodes and the bias node bypass engage() and have their
        output_value set directly by NEATBrain.feed_forward().
        """
        total = sum(
            conn.weight * conn.from_node.output_value
            for conn in self.output_connections  # these are INCOMING for the receiver
            if conn.enabled and conn.to_node is self
        )
        # Sigmoid with slope 4.9 (standard NEAT)
        self.output_value = 1.0 / (1.0 + math.exp(-4.9 * total))

    def clone(self) -> "Node":
        """Return a lightweight clone (connections not copied here)."""
        n = Node(self.number, self.layer)
        n.output_value = self.output_value
        return n

    def __repr__(self) -> str:
        return f"Node(no={self.number}, layer={self.layer}, val={self.output_value:.3f})"


# ---------------------------------------------------------------------------
# ConnectionGene
# ---------------------------------------------------------------------------
class ConnectionGene:
    """A directed, weighted edge between two nodes.

    Attributes:
        from_node:      Source Node.
        to_node:        Target Node.
        weight:         Synaptic weight in [-1, 1] (or perturbed beyond).
        innovation_no:  Global innovation number for crossover alignment.
        enabled:        If False the connection exists structurally but is
                        ignored during feed-forward.
    """

    def __init__(
        self,
        from_node: Node,
        to_node: Node,
        weight: float,
        innovation_no: int,
    ) -> None:
        self.from_node: Node = from_node
        self.to_node: Node = to_node
        self.weight: float = weight
        self.innovation_no: int = innovation_no
        self.enabled: bool = True

    def clone(self, from_node: Node, to_node: Node) -> "ConnectionGene":
        """Return a copy bound to the supplied node instances."""
        c = ConnectionGene(from_node, to_node, self.weight, self.innovation_no)
        c.enabled = self.enabled
        return c

    def __repr__(self) -> str:
        status = "ON" if self.enabled else "OFF"
        return (
            f"Conn({self.from_node.number}->{self.to_node.number} "
            f"w={self.weight:.3f} innov={self.innovation_no} {status})"
        )


# ---------------------------------------------------------------------------
# ConnectionHistory
# ---------------------------------------------------------------------------
class ConnectionHistory:
    """Records a structural mutation so the same topological change always
    receives the same innovation number across different genomes in the same
    generation.

    Attributes:
        from_node_no:          Source node number at time of mutation.
        to_node_no:            Target node number at time of mutation.
        innovation_no:         The innovation number assigned to this edge.
        genome_innovation_nos: Sorted list of all innovation numbers present in
                               the genome that produced this mutation (used to
                               confirm the network context is identical).
    """

    def __init__(
        self,
        from_node_no: int,
        to_node_no: int,
        innovation_no: int,
        genome_innovation_nos: list,
    ) -> None:
        self.from_node_no: int = from_node_no
        self.to_node_no: int = to_node_no
        self.innovation_no: int = innovation_no
        self.genome_innovation_nos: list = list(genome_innovation_nos)

    def matches(self, genome: "NEATBrain", from_node: Node, to_node: Node) -> bool:
        """Return True if this history entry matches the given genome + edge.

        Matching requires the same endpoints *and* the same set of innovation
        numbers, ensuring structural context is identical.
        """
        if from_node.number != self.from_node_no:
            return False
        if to_node.number != self.to_node_no:
            return False
        genome_innov = sorted(g.innovation_no for g in genome.genes)
        return genome_innov == sorted(self.genome_innovation_nos)


# ---------------------------------------------------------------------------
# NEATBrain (Genome)
# ---------------------------------------------------------------------------
class NEATBrain:
    """A NEAT genome: a collection of nodes and connection genes.

    Inputs  (5): car_angle, on_ground, angular_velocity,
                 terrain_height_ahead, terrain_slope
    Outputs (2): gas, brake

    Attributes:
        inputs:         Number of input neurons.
        outputs:        Number of output neurons.
        genes:          List[ConnectionGene] — the genome's edges.
        nodes:          List[Node] — all nodes.
        layers:         Current number of layers (starts at 2).
        next_node:      Counter for assigning new node numbers.
        bias_node_idx:  Index into self.nodes for the bias node.
        network:        Topologically ordered list of nodes for feed-forward.
    """

    INPUTS: int = 5
    OUTPUTS: int = 2

    def __init__(
        self,
        inputs: int = 5,
        outputs: int = 2,
        crossover: bool = False,
    ) -> None:
        self.inputs: int = inputs
        self.outputs: int = outputs
        self.genes: list = []        # List[ConnectionGene]
        self.nodes: list = []        # List[Node]
        self.layers: int = 2
        self.next_node: int = 0
        self.network: list = []      # topologically sorted for feed-forward
        self.bias_node_idx: int = 0

        if crossover:
            # Empty genome — structure filled in by crossover()
            return

        # Create input nodes (layer 0)
        for _ in range(self.inputs):
            self.nodes.append(Node(self.next_node, layer=0))
            self.next_node += 1

        # Create output nodes (layer 1)
        for _ in range(self.outputs):
            self.nodes.append(Node(self.next_node, layer=1))
            self.next_node += 1

        # Bias node (layer 0, output always 1.0)
        self.nodes.append(Node(self.next_node, layer=0))
        self.bias_node_idx = len(self.nodes) - 1
        self.nodes[self.bias_node_idx].output_value = 1.0
        self.next_node += 1

    # ------------------------------------------------------------------
    # Structural helpers
    # ------------------------------------------------------------------

    def get_node(self, number: int):
        """Return the Node whose number matches, or None."""
        for n in self.nodes:
            if n.number == number:
                return n
        return None

    def connect_nodes(self) -> None:
        """Rebuild each node's output_connections list from self.genes.

        Must be called whenever genes are added or nodes restructured.
        """
        for node in self.nodes:
            node.output_connections = []
        for gene in self.genes:
            gene.from_node.output_connections.append(gene)

    def generate_network(self) -> None:
        """Topological sort: group nodes by layer, flatten into self.network."""
        self.connect_nodes()
        self.network = []
        for layer_idx in range(self.layers):
            for node in self.nodes:
                if node.layer == layer_idx:
                    self.network.append(node)

    def fully_connect(self, innovation_history: list) -> None:
        """Connect every input (+ bias) node to every output node."""
        for inp in self.nodes:
            if inp.layer != 0:
                continue
            for out in self.nodes:
                if out.layer != 1:
                    continue
                innov = self.get_innovation_number(innovation_history, inp, out)
                weight = random.uniform(-1.0, 1.0)
                self.genes.append(ConnectionGene(inp, out, weight, innov))
        self.generate_network()

    def get_innovation_number(
        self, history: list, from_node: Node, to_node: Node
    ) -> int:
        """Return existing innovation number for this edge, or create a new one."""
        for h in history:
            if h.matches(self, from_node, to_node):
                return h.innovation_no
        # New structural innovation
        new_innov = _new_innovation()
        genome_innovs = [g.innovation_no for g in self.genes]
        history.append(
            ConnectionHistory(from_node.number, to_node.number, new_innov, genome_innovs)
        )
        return new_innov

    # ------------------------------------------------------------------
    # Feed-forward
    # ------------------------------------------------------------------

    def feed_forward(self, input_values: list) -> list:
        """Propagate inputs through the network and return output activations.

        Args:
            input_values: Exactly self.inputs floats.

        Returns:
            List of self.outputs floats (one per output node).
        """
        # Set input node values
        for i in range(self.inputs):
            self.nodes[i].output_value = input_values[i]
        # Bias always 1.0
        self.nodes[self.bias_node_idx].output_value = 1.0

        # Engage each node in topological order
        for node in self.network:
            # Input nodes and bias are already set; hidden + output use engage()
            if node.layer != 0:
                node.engage()

        # Collect output values
        output_values = [
            node.output_value
            for node in self.nodes
            if node.layer == 1
        ]
        # Reset node states for next call
        for node in self.nodes:
            node.output_connections = []
        self.connect_nodes()
        return output_values

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def mutate(self, innovation_history: list) -> None:
        """Apply stochastic mutations to this genome.

        Probabilities:
            80% — weight mutation (each weight: 90% perturb, 10% random new)
             5% — add a new connection
             3% — add a new hidden node
        """
        if not self.genes:
            self.add_connection(innovation_history)
            return

        if random.random() < 0.80:
            for gene in self.genes:
                if random.random() < 0.90:
                    # Gaussian perturbation ±0.1
                    gene.weight += random.gauss(0, 0.1)
                    gene.weight = max(-2.0, min(2.0, gene.weight))
                else:
                    gene.weight = random.uniform(-1.0, 1.0)

        if random.random() < 0.05:
            self.add_connection(innovation_history)

        if random.random() < 0.03:
            self.add_node(innovation_history)

    def add_connection(self, innovation_history: list) -> None:
        """Add a random new connection between two previously unconnected nodes.

        Respects layer ordering (from_node.layer < to_node.layer) and skips
        pairs that are already connected.
        """
        if len(self.nodes) < 2:
            return

        def already_connected(a: Node, b: Node) -> bool:
            return any(
                g.from_node.number == a.number and g.to_node.number == b.number
                for g in self.genes
            )

        # Try up to 100 times to find a valid pair
        for _ in range(100):
            a = random.choice(self.nodes)
            b = random.choice(self.nodes)
            if a is b:
                continue
            if a.layer == b.layer:
                continue
            if a.layer > b.layer:
                a, b = b, a   # enforce forward direction
            if already_connected(a, b):
                continue
            innov = self.get_innovation_number(innovation_history, a, b)
            weight = random.uniform(-1.0, 1.0)
            self.genes.append(ConnectionGene(a, b, weight, innov))
            self.generate_network()
            return

    def add_node(self, innovation_history: list) -> None:
        """Split an existing enabled connection with a new hidden node.

        The original connection is disabled; two new connections replace it:
            from_node -(weight 1.0)-> new_node -(old_weight)-> to_node
        """
        enabled = [g for g in self.genes if g.enabled]
        if not enabled:
            return
        gene_to_split = random.choice(enabled)
        gene_to_split.enabled = False

        # New hidden node placed in its own layer
        new_node = Node(self.next_node, layer=gene_to_split.from_node.layer + 1)
        self.next_node += 1

        # Push layers apart if needed
        if new_node.layer == gene_to_split.to_node.layer:
            for node in self.nodes:
                if node.layer >= new_node.layer:
                    node.layer += 1
            self.layers += 1

        self.nodes.append(new_node)

        # Connection: from_node -> new_node  (weight 1 to preserve signal)
        innov1 = self.get_innovation_number(
            innovation_history, gene_to_split.from_node, new_node
        )
        self.genes.append(
            ConnectionGene(gene_to_split.from_node, new_node, 1.0, innov1)
        )

        # Connection: new_node -> to_node  (preserves old weight)
        innov2 = self.get_innovation_number(
            innovation_history, new_node, gene_to_split.to_node
        )
        self.genes.append(
            ConnectionGene(new_node, gene_to_split.to_node, gene_to_split.weight, innov2)
        )

        # Bias -> new_node  (weight 0)
        bias_node = self.nodes[self.bias_node_idx]
        innov3 = self.get_innovation_number(innovation_history, bias_node, new_node)
        self.genes.append(ConnectionGene(bias_node, new_node, 0.0, innov3))

        self.generate_network()

    # ------------------------------------------------------------------
    # Crossover & cloning
    # ------------------------------------------------------------------

    def clone(self) -> "NEATBrain":
        """Return a deep copy of this genome."""
        baby = NEATBrain(self.inputs, self.outputs, crossover=True)
        baby.layers = self.layers
        baby.next_node = self.next_node
        baby.bias_node_idx = self.bias_node_idx

        # Clone nodes
        for node in self.nodes:
            baby.nodes.append(node.clone())

        # Clone genes (rebind to baby's node instances)
        for gene in self.genes:
            fn = baby.get_node(gene.from_node.number)
            tn = baby.get_node(gene.to_node.number)
            if fn is not None and tn is not None:
                baby.genes.append(gene.clone(fn, tn))

        baby.generate_network()
        return baby

    def crossover(self, parent2: "NEATBrain") -> "NEATBrain":
        """Produce a child genome via NEAT crossover.

        Matching genes are inherited randomly; disjoint/excess genes come
        from the fitter parent (self is assumed to be the fitter parent).

        Args:
            parent2: The less-fit (or equally fit) parent.

        Returns:
            A new NEATBrain child genome.
        """
        child = NEATBrain(self.inputs, self.outputs, crossover=True)
        child.layers = self.layers
        child.next_node = self.next_node
        child.bias_node_idx = self.bias_node_idx

        # Clone nodes from fitter parent (self)
        for node in self.nodes:
            child.nodes.append(node.clone())

        p2_innov = {g.innovation_no: g for g in parent2.genes}

        for gene in self.genes:
            p2_gene = p2_innov.get(gene.innovation_no)
            if p2_gene is not None:
                # Matching gene — pick randomly
                chosen = random.choice([gene, p2_gene])
                enabled = gene.enabled and p2_gene.enabled
                if not (gene.enabled and p2_gene.enabled):
                    enabled = random.random() < 0.75   # 75% chance re-enable
            else:
                # Disjoint/excess — always from fitter parent (self)
                chosen = gene
                enabled = gene.enabled

            fn = child.get_node(chosen.from_node.number)
            tn = child.get_node(chosen.to_node.number)
            if fn is not None and tn is not None:
                c = chosen.clone(fn, tn)
                c.enabled = enabled
                child.genes.append(c)

        child.generate_network()
        return child

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def save_to_dict(self) -> dict:
        """Serialise genome to a JSON-safe dictionary."""
        return {
            "inputs": self.inputs,
            "outputs": self.outputs,
            "layers": self.layers,
            "next_node": self.next_node,
            "bias_node_idx": self.bias_node_idx,
            "nodes": [
                {"number": n.number, "layer": n.layer} for n in self.nodes
            ],
            "genes": [
                {
                    "from": g.from_node.number,
                    "to": g.to_node.number,
                    "weight": g.weight,
                    "innovation_no": g.innovation_no,
                    "enabled": g.enabled,
                }
                for g in self.genes
            ],
        }

    @classmethod
    def load_from_dict(cls, data: dict) -> "NEATBrain":
        """Deserialise a genome from a dictionary produced by save_to_dict()."""
        brain = cls(data["inputs"], data["outputs"], crossover=True)
        brain.layers = data["layers"]
        brain.next_node = data["next_node"]
        brain.bias_node_idx = data["bias_node_idx"]

        for nd in data["nodes"]:
            brain.nodes.append(Node(nd["number"], nd["layer"]))

        for gd in data["genes"]:
            fn = brain.get_node(gd["from"])
            tn = brain.get_node(gd["to"])
            if fn is None or tn is None:
                continue
            gene = ConnectionGene(fn, tn, gd["weight"], gd["innovation_no"])
            gene.enabled = gd["enabled"]
            brain.genes.append(gene)

        brain.generate_network()
        return brain

    def __repr__(self) -> str:
        return (
            f"NEATBrain(nodes={len(self.nodes)}, genes={len(self.genes)}, "
            f"layers={self.layers})"
        )


# ---------------------------------------------------------------------------
# Species
# ---------------------------------------------------------------------------
class Species:
    """Groups genetically similar players together for fitness sharing.

    Attributes:
        players:                Members of the species this generation.
        best_fitness:           Historical best fitness seen in this species.
        champ:                  The player with the highest fitness (cloned as champion).
        average_fitness:        Mean fitness of current members.
        staleness:              Generations without improvement.
        rep:                    Representative genome for compatibility testing.
        excess_coeff:           Weight for excess/disjoint gene count in distance.
        weight_diff_coeff:      Weight for average weight difference in distance.
        compatibility_threshold: Maximum distance to be in the same species.
    """

    excess_coeff: float = 1.0
    weight_diff_coeff: float = 0.5
    compatibility_threshold: float = 3.0

    def __init__(self, player=None) -> None:
        self.players: list = []          # List[AIPlayer]
        self.best_fitness: float = 0.0
        self.champ = None                # AIPlayer
        self.average_fitness: float = 0.0
        self.staleness: int = 0
        self.rep: "NEATBrain | None" = None

        if player is not None:
            self.players.append(player)
            self.best_fitness = player.fitness
            self.rep = player.brain.clone()
            self.champ = player.clone_for_replay()

    # ------------------------------------------------------------------

    def same_species(self, genome: NEATBrain) -> bool:
        """Return True if the genome is compatible with this species."""
        if self.rep is None:
            return False
        excess_disjoint = self.get_excess_disjoint(genome, self.rep)
        avg_w = self.average_weight_diff(genome, self.rep)
        normalise = max(len(genome.genes), 1)
        distance = (
            self.excess_coeff * excess_disjoint / normalise
            + self.weight_diff_coeff * avg_w
        )
        return distance < self.compatibility_threshold

    def get_excess_disjoint(self, brain1: NEATBrain, brain2: NEATBrain) -> float:
        """Count of non-matching genes between two genomes."""
        innovs2 = {g.innovation_no for g in brain2.genes}
        innovs1 = {g.innovation_no for g in brain1.genes}
        matching = innovs1 & innovs2
        return len(innovs1) + len(innovs2) - 2 * len(matching)

    def average_weight_diff(self, brain1: NEATBrain, brain2: NEATBrain) -> float:
        """Mean absolute weight difference of matching genes."""
        if not brain1.genes or not brain2.genes:
            return 0.0
        b2_map = {g.innovation_no: g.weight for g in brain2.genes}
        diffs = [
            abs(g.weight - b2_map[g.innovation_no])
            for g in brain1.genes
            if g.innovation_no in b2_map
        ]
        return sum(diffs) / len(diffs) if diffs else 0.0

    def sort_species(self) -> None:
        """Sort players by fitness descending and update staleness."""
        self.players.sort(key=lambda p: p.fitness, reverse=True)
        if not self.players:
            self.staleness += 1
            return
        if self.players[0].fitness > self.best_fitness:
            self.best_fitness = self.players[0].fitness
            self.rep = self.players[0].brain.clone()
            self.champ = self.players[0].clone_for_replay()
            self.staleness = 0
        else:
            self.staleness += 1

    def set_average(self) -> None:
        """Compute and store mean fitness of current members."""
        if not self.players:
            self.average_fitness = 0.0
            return
        self.average_fitness = sum(p.fitness for p in self.players) / len(self.players)

    def give_me_baby(self, innovation_history: list) -> NEATBrain:
        """Produce a child genome via crossover or clone+mutate.

        If only one member, clone and mutate.  Otherwise with 25% chance
        clone the best; otherwise crossover two random members.
        """
        if len(self.players) == 1 or random.random() < 0.25:
            baby = random.choice(self.players).brain.clone()
        else:
            p1 = random.choice(self.players)
            p2 = random.choice(self.players)
            if p1.fitness >= p2.fitness:
                baby = p1.brain.crossover(p2.brain)
            else:
                baby = p2.brain.crossover(p1.brain)
        baby.mutate(innovation_history)
        return baby

    def kill_bottom_half(self) -> None:
        """Remove the worst-performing 50% of players."""
        keep = max(1, len(self.players) // 2)
        self.players = self.players[:keep]

    def fitness_sharing(self) -> None:
        """Divide each player's fitness by species size (fitness sharing)."""
        size = len(self.players)
        if size == 0:
            return
        for player in self.players:
            player.fitness /= size


# ---------------------------------------------------------------------------
# AIPlayer
# ---------------------------------------------------------------------------
class AIPlayer:
    """Links a NEATBrain to game-state observations and fitness tracking.

    Attributes:
        brain:    The underlying NEAT genome.
        fitness:  Computed fitness score.
        score:    Raw distance / game score.
        dead:     Whether this player has died (episode ended).
        lifespan: Number of ticks survived.
        vision:   Most recent observation vector fed into the brain.
        decision: Most recent output vector returned by the brain.
    """

    def __init__(self, brain: "NEATBrain | None" = None) -> None:
        if brain is None:
            self.brain = NEATBrain()
        else:
            self.brain = brain
        self.fitness: float = 0.0
        self.score: float = 0.0
        self.dead: bool = False
        self.lifespan: int = 0
        self.vision: list = []
        self.decision: list = []

    # ------------------------------------------------------------------

    def look(self, game_state: dict) -> list:
        """Convert raw game-state dict into a normalised 5-float input vector.

        Expected keys:
            car_angle        (radians, 0–2π)
            on_ground        (bool or 0/1)
            angular_velocity (float, roughly –4..4)
            terrain_height   (float, 0..10)
            terrain_slope    (float, –3..3)

        Returns:
            List of 5 floats in range [–1, 1] or [0, 1].
        """
        car_angle = float(game_state.get("car_angle", 0.0))
        on_ground = float(bool(game_state.get("on_ground", False)))
        ang_vel = float(game_state.get("angular_velocity", 0.0))
        t_height = float(game_state.get("terrain_height", 0.0))
        t_slope = float(game_state.get("terrain_slope", 0.0))

        normed_angle = (car_angle % (2 * math.pi)) / (2 * math.pi)
        normed_ang_vel = max(-1.0, min(1.0, ang_vel / 4.0))
        normed_height = max(0.0, min(1.0, t_height / 10.0))
        normed_slope = max(-1.0, min(1.0, t_slope / 3.0))

        self.vision = [
            normed_angle,
            on_ground,
            normed_ang_vel,
            normed_height,
            normed_slope,
        ]
        return self.vision

    def think(self) -> list:
        """Run the brain on the current vision; store and return decisions."""
        if not self.vision:
            self.decision = [0.0] * NEATBrain.OUTPUTS
            return self.decision
        self.decision = self.brain.feed_forward(self.vision)
        return self.decision

    def calculate_fitness(self) -> None:
        """Fitness = score² (rewards going far more than barely surviving)."""
        self.fitness = self.score ** 2

    def clone(self) -> "AIPlayer":
        """Return a full clone (new brain, reset stats)."""
        p = AIPlayer(self.brain.clone())
        p.fitness = self.fitness
        p.score = self.score
        return p

    def clone_for_replay(self) -> "AIPlayer":
        """Return a lightweight clone suitable for champion replay."""
        p = AIPlayer(self.brain.clone())
        p.fitness = self.fitness
        p.score = self.score
        return p

    def __repr__(self) -> str:
        return (
            f"AIPlayer(score={self.score:.1f}, fitness={self.fitness:.1f}, "
            f"dead={self.dead}, lifespan={self.lifespan})"
        )


# ---------------------------------------------------------------------------
# NEATPopulation
# ---------------------------------------------------------------------------
class NEATPopulation:
    """Manages the full NEAT evolutionary population.

    Attributes:
        pop_size:               Target population size.
        players:                Current generation of AIPlayer instances.
        best_player:            Player with the all-time highest score.
        best_score:             All-time best raw score.
        gen:                    Current generation index (1-based).
        innovation_history:     Shared list of ConnectionHistory entries.
        species:                List of active Species.
        mass_extinction_event:  If True, all species except the top two are
                                culled at the next natural_selection() call.
    """

    def __init__(self, pop_size: int = 50) -> None:
        self.pop_size: int = pop_size
        self.players: list = []          # List[AIPlayer]
        self.best_player: "AIPlayer | None" = None
        self.best_score: float = 0.0
        self.gen: int = 1
        self.innovation_history: list = []   # List[ConnectionHistory]
        self.species: list = []              # List[Species]
        self.mass_extinction_event: bool = False

        # Initialise population
        for _ in range(pop_size):
            p = AIPlayer()
            p.brain.fully_connect(self.innovation_history)
            p.brain.generate_network()
            self.players.append(p)

    # ------------------------------------------------------------------

    def all_dead(self) -> bool:
        """Return True when every player in the population is dead."""
        return all(p.dead for p in self.players)

    def natural_selection(self) -> None:
        """Run one generation of NEAT evolution.

        Steps:
            1. Speciate players.
            2. Calculate (shared) fitness.
            3. Sort species by best fitness.
            4. Kill stale species.
            5. Kill bad species (expected offspring < 1).
            6. Reproduce to refill population.
            7. Increment generation counter.
        """
        self.speciate()
        self.calculate_fitness()
        self.sort_species()

        if self.mass_extinction_event:
            self._mass_extinction()
            self.mass_extinction_event = False
        else:
            self.kill_stale_species()

        self.kill_extinct()
        self.sort_species()

        # Determine offspring counts per species
        total_average = sum(s.average_fitness for s in self.species) or 1.0
        new_players: list = []

        for sp in self.species:
            # Keep champion unchanged if species large enough
            if sp.champ is not None:
                champion = sp.champ.clone_for_replay()
                champion.dead = False
                champion.score = 0.0
                champion.fitness = 0.0
                champion.lifespan = 0
                new_players.append(champion)

            offspring_count = int(sp.average_fitness / total_average * self.pop_size) - 1
            for _ in range(max(0, offspring_count)):
                baby_brain = sp.give_me_baby(self.innovation_history)
                baby = AIPlayer(baby_brain)
                new_players.append(baby)

        # Top up with offspring from best species if short
        while len(new_players) < self.pop_size:
            if self.species:
                baby_brain = self.species[0].give_me_baby(self.innovation_history)
            else:
                baby_brain = NEATBrain()
                baby_brain.fully_connect(self.innovation_history)
            new_players.append(AIPlayer(baby_brain))

        self.players = new_players[: self.pop_size]
        self.gen += 1

        for p in self.players:
            p.brain.generate_network()

    # ------------------------------------------------------------------
    # Private helpers

    def speciate(self) -> None:
        """Assign each player to a compatible species (or create a new one)."""
        for sp in self.species:
            sp.players = []

        for player in self.players:
            placed = False
            for sp in self.species:
                if sp.same_species(player.brain):
                    sp.players.append(player)
                    placed = True
                    break
            if not placed:
                self.species.append(Species(player))

    def calculate_fitness(self) -> None:
        """Compute fitness for each player and apply fitness sharing."""
        for player in self.players:
            player.calculate_fitness()
        for sp in self.species:
            sp.fitness_sharing()

    def sort_species(self) -> None:
        """Sort each species internally, then sort species list by best fitness."""
        for sp in self.species:
            sp.sort_species()
            sp.set_average()
        self.species.sort(key=lambda s: s.best_fitness, reverse=True)

    def kill_extinct(self) -> None:
        """Remove species with no living members."""
        self.species = [s for s in self.species if s.players]

    def kill_stale_species(self) -> None:
        """Remove species that have not improved in 15+ generations (keep top 2)."""
        surviving = []
        for i, sp in enumerate(self.species):
            if i < 2 or sp.staleness < 15:
                surviving.append(sp)
        self.species = surviving

    def _mass_extinction(self) -> None:
        """Keep only the top 2 species; wipe the rest."""
        self.species = self.species[:2]

    def get_best_player(self) -> "AIPlayer | None":
        """Return the player with the highest score this generation."""
        if not self.players:
            return None
        best = max(self.players, key=lambda p: p.score)
        if best.score > self.best_score:
            self.best_score = best.score
            self.best_player = best.clone_for_replay()
        return best

    def __repr__(self) -> str:
        return (
            f"NEATPopulation(gen={self.gen}, pop={len(self.players)}, "
            f"species={len(self.species)}, best_score={self.best_score:.1f})"
        )


# ---------------------------------------------------------------------------
# __main__ — smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import time

    print("=" * 60)
    print("NEAT Brain — Smoke Test")
    print("=" * 60)

    POP = 5
    GENS = 3
    TICKS_PER_EPISODE = 20

    population = NEATPopulation(pop_size=POP)
    print(f"Initialised population: {population}\n")

    for gen_idx in range(GENS):
        t0 = time.time()

        # Simulate episodes until all players are dead
        tick = 0
        while not population.all_dead() and tick < TICKS_PER_EPISODE:
            for player in population.players:
                if player.dead:
                    continue
                # Dummy game state
                game_state = {
                    "car_angle": random.uniform(0, 2 * math.pi),
                    "on_ground": random.random() > 0.3,
                    "angular_velocity": random.uniform(-4, 4),
                    "terrain_height": random.uniform(0, 10),
                    "terrain_slope": random.uniform(-3, 3),
                }
                player.look(game_state)
                decision = player.think()
                # Simulate score (gas - brake ~ forward progress)
                gas, brake = decision[0], decision[1]
                player.score += max(0.0, gas - brake * 0.5) * 0.5
                player.lifespan += 1
                if tick == TICKS_PER_EPISODE - 1:
                    player.dead = True
            tick += 1

        best = population.get_best_player()
        elapsed = time.time() - t0

        print(
            f"Gen {population.gen:>3} | "
            f"species={len(population.species):>2} | "
            f"best_score={population.best_score:>6.2f} | "
            f"time={elapsed:.3f}s"
        )

        # Evolve
        population.natural_selection()

    print("\nSmoke test complete — NEAT engine is working correctly.")
