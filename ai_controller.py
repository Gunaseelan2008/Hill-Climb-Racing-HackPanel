"""
ai_controller.py – AI Auto-Play Controller for Hill Climb Racing Trainer V2

Bridges the NEAT brain with the live game:
  1. Reads game state from memory (car angle, speed, etc.)
  2. Feeds state into the NEAT neural network
  3. Presses/releases keyboard keys based on the network's output
  4. Tracks score (distance / fuel) for fitness evaluation
  5. Runs in a background daemon thread — does not block the UI
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Optional imports — handle gracefully so the module loads even without them
# ---------------------------------------------------------------------------
try:
    import keyboard  # type: ignore
    _KEYBOARD_AVAILABLE = True
except ImportError:
    keyboard = None  # type: ignore
    _KEYBOARD_AVAILABLE = False
    logging.warning("ai_controller: 'keyboard' library not found — key presses disabled.")

try:
    import pymem  # type: ignore
    _PYMEM_AVAILABLE = True
except ImportError:
    pymem = None  # type: ignore
    _PYMEM_AVAILABLE = False
    logging.warning("ai_controller: 'pymem' library not found — memory reads disabled.")

try:
    from neat_brain import NEATBrain, NEATPopulation, AIPlayer  # type: ignore
    _NEAT_AVAILABLE = True
except ImportError:
    NEATBrain = None  # type: ignore
    NEATPopulation = None  # type: ignore
    AIPlayer = None  # type: ignore
    _NEAT_AVAILABLE = False
    logging.warning("ai_controller: 'neat_brain' module not found — NEAT features disabled.")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ---------------------------------------------------------------------------
# Memory layout constants
# ---------------------------------------------------------------------------
FUEL_BASE_OFFSET: int = 0x0028CA2C   # Static offset from main module base
FUEL_PTR_OFFSET: int = 0x2A8         # Pointer chain hop to reach the float


# ===========================================================================
# GameStateReader
# ===========================================================================
class GameStateReader:
    """Reads live game values from memory using pymem."""

    # Fields that have not been reverse-engineered yet.  Once found via Cheat
    # Engine the TODO comments below can be replaced with real reads.
    _TODO_FIELDS = {
        "car_angle",
        "angular_velocity",
        "terrain_height",
        "terrain_slope",
        "distance",
    }

    def __init__(self, pm, base_address: int, module_base: int) -> None:
        """
        Parameters
        ----------
        pm           : pymem.Pymem instance (may be None if game not attached)
        base_address : main module base address
        module_base  : cocos2d-win10.dll base address
        """
        self.pm = pm
        self.base_address = base_address
        self.module_base = module_base

        # Track which TODO fields have already emitted a debug note so we
        # only log once per session rather than flooding the log.
        self._todo_logged: set[str] = set()

    # ------------------------------------------------------------------
    def read_state(self) -> dict:
        """
        Returns a dict with keys:
          car_angle        float  0.0  (TODO: find offset with Cheat Engine)
          angular_velocity float  0.0  (TODO: find offset)
          on_ground        float  1.0  (default: assume on ground)
          terrain_height   float  0.0  (TODO: find offset)
          terrain_slope    float  0.0  (TODO: find offset)
          fuel             float       (read from memory via pointer chain)
          distance         float  0.0  (TODO: find offset)
        """
        state: dict = {}

        # ── Fields with known memory offsets ──────────────────────────
        state["fuel"] = self.read_fuel()
        state["on_ground"] = 1.0  # Reasonable default; TODO: find actual flag

        # ── TODO stub fields ──────────────────────────────────────────
        for field in ("car_angle", "angular_velocity", "terrain_height",
                      "terrain_slope", "distance"):
            if field not in self._todo_logged:
                logger.debug(
                    "GameStateReader: '%s' has no memory offset yet — "
                    "returning 0.0.  Fill in with Cheat Engine offset later.",
                    field,
                )
                self._todo_logged.add(field)
            # TODO: replace 0.0 with real pymem read once offset is known
            state[field] = 0.0

        return state

    # ------------------------------------------------------------------
    def read_fuel(self) -> float:
        """
        Read fuel from: base_address + FUEL_BASE_OFFSET  →  +FUEL_PTR_OFFSET
        Returns 0.0 if the game is not attached or the read fails.
        """
        if self.pm is None or not _PYMEM_AVAILABLE:
            return 0.0

        try:
            # Resolve pointer chain:  [base_address + FUEL_BASE_OFFSET] + FUEL_PTR_OFFSET
            pointer_addr: int = self.base_address + FUEL_BASE_OFFSET
            target_addr: int = self.pm.read_int(pointer_addr) + FUEL_PTR_OFFSET
            fuel: float = self.pm.read_float(target_addr)
            return fuel
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("read_fuel failed: %s", exc)
            return 0.0


# ===========================================================================
# AIController
# ===========================================================================
class AIController:
    """
    Main AI control loop that runs in a background daemon thread.

    Usage (manual mode)::

        ctrl = AIController()
        ctrl.state_reader = GameStateReader(pm, base_addr, mod_base)
        ctrl.start_manual(my_brain)
        ...
        ctrl.stop()

    Usage (training mode)::

        ctrl = AIController()
        ctrl.state_reader = GameStateReader(pm, base_addr, mod_base)
        ctrl.start_training(pop_size=50)
        ...
        ctrl.stop()
    """

    # Keyboard keys used for game control
    GAS_KEY: str   = "right"
    BRAKE_KEY: str = "left"

    # Dummy game state used when no state reader is attached
    _DUMMY_STATE: dict = {
        "car_angle":        0.0,
        "on_ground":        1.0,
        "angular_velocity": 0.0,
        "terrain_height":   0.0,
        "terrain_slope":    0.0,
        "fuel":             0.0,
        "distance":         0.0,
    }

    def __init__(self) -> None:
        self.running: bool = False
        self.paused: bool  = False

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Set by caller before start_*()
        self.brain = None          # NEATBrain instance (manual mode)
        self.state_reader: Optional[GameStateReader] = None

        # ── Thread-safe stats ──────────────────────────────────────────
        self._gen: int              = 0
        self._best_score: float     = 0.0
        self._current_score: float  = 0.0
        self._species_count: int    = 0
        self._last_decision: list   = [0.0, 0.0]
        self._lock = threading.Lock()

        # NEAT population (created in start_training)
        self.population = None

        # Seconds between AI decisions (20 Hz default)
        self.tick_interval: float = 0.05

        # Key state tracker to avoid redundant press/release calls
        self._keys_pressed: set[str] = set()

    # ==================================================================
    # start / stop
    # ==================================================================
    def start_manual(self, brain) -> None:
        """Start AI using a single pre-loaded brain (no evolution)."""
        if self.running:
            logger.warning("AIController: already running — call stop() first.")
            return

        self.brain = brain
        self._reset_stop_event()
        self.running = True
        self.paused  = False

        self._thread = threading.Thread(
            target=self._loop_manual,
            name="AIController-Manual",
            daemon=True,
        )
        self._thread.start()
        logger.info("AIController: manual mode started.")

    def start_training(self, pop_size: int = 50) -> None:
        """Start full NEAT training with a fresh population."""
        if self.running:
            logger.warning("AIController: already running — call stop() first.")
            return

        if not _NEAT_AVAILABLE or NEATPopulation is None:
            logger.error("AIController: neat_brain not available — cannot start training.")
            return

        # Build a fresh population; NEATPopulation is expected to accept
        # (pop_size) or (pop_size, input_size, output_size).
        try:
            # State vector has 6 inputs; outputs are [gas, brake]
            self.population = NEATPopulation(pop_size=pop_size,
                                             input_size=6,
                                             output_size=2)
        except TypeError:
            # Fallback: single-argument constructor
            self.population = NEATPopulation(pop_size)

        self._reset_stop_event()
        self.running = True
        self.paused  = False

        self._thread = threading.Thread(
            target=self._loop_training,
            name="AIController-Training",
            daemon=True,
        )
        self._thread.start()
        logger.info("AIController: training mode started (pop_size=%d).", pop_size)

    def stop(self) -> None:
        """Stop the AI loop and release all held keys."""
        if not self.running:
            return

        self._stop_event.set()
        self.running = False
        self.paused  = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

        self._release_all_keys()
        logger.info("AIController: stopped.")

    def pause(self) -> None:
        """Toggle pause / resume."""
        self.paused = not self.paused
        if self.paused:
            self._release_all_keys()
            logger.info("AIController: paused.")
        else:
            logger.info("AIController: resumed.")

    # ==================================================================
    # Control loops (run in background thread)
    # ==================================================================
    def _loop_manual(self) -> None:
        """Manual mode: use a single fixed brain, loop indefinitely."""
        logger.debug("_loop_manual: thread started.")

        while not self._stop_event.is_set():
            if self.paused:
                time.sleep(0.1)
                continue

            if self.brain is not None:
                self._tick(self.brain)

            time.sleep(self.tick_interval)

        self._release_all_keys()
        logger.debug("_loop_manual: thread exited.")

    def _loop_training(self) -> None:
        """Training mode: evolve population across generations."""
        logger.debug("_loop_training: thread started.")

        if self.population is None:
            logger.error("_loop_training: population is None — aborting.")
            return

        generation: int = 0

        while not self._stop_event.is_set():
            generation += 1
            with self._lock:
                self._gen = generation

            logger.info("Training — generation %d", generation)

            # Retrieve the list of brains/players for this generation.
            # We try common attribute names used by NEATPopulation.
            players = None
            for attr in ("players", "population", "genomes", "individuals"):
                players = getattr(self.population, attr, None)
                if players is not None:
                    break

            if players is None:
                # Fallback: treat population itself as iterable
                try:
                    players = list(self.population)
                except TypeError:
                    logger.error("_loop_training: cannot iterate population — aborting.")
                    break

            species_count = len(players)
            with self._lock:
                self._species_count = species_count

            # ── Evaluate each player/genome ────────────────────────────
            for idx, player in enumerate(players):
                if self._stop_event.is_set():
                    break

                # Resolve the brain for this player
                brain = player.brain if hasattr(player, "brain") else player

                lifespan_ticks: int   = 0
                episode_score: float  = 0.0

                # Run the player for up to 400 ticks (~20 s at 20 Hz)
                max_ticks: int = 400
                for _ in range(max_ticks):
                    if self._stop_event.is_set():
                        break
                    if self.paused:
                        time.sleep(0.1)
                        continue

                    self._tick(brain)
                    lifespan_ticks += 1

                    # Score proxy: lifespan ticks (distance not yet readable)
                    # TODO: replace with real distance when memory offset known
                    episode_score = float(lifespan_ticks)

                    with self._lock:
                        self._current_score = episode_score

                    time.sleep(self.tick_interval)

                # Assign fitness
                if hasattr(player, "fitness"):
                    player.fitness = episode_score
                elif hasattr(player, "score"):
                    player.score = episode_score

                with self._lock:
                    if episode_score > self._best_score:
                        self._best_score = episode_score
                        # Cache best brain so it can be saved later
                        self._best_brain_ref = brain

                logger.debug(
                    "  Player %d/%d — ticks=%d score=%.1f",
                    idx + 1, species_count, lifespan_ticks, episode_score,
                )

                self._release_all_keys()

            if self._stop_event.is_set():
                break

            # Evolve population to next generation
            try:
                self.population.evolve()
            except AttributeError:
                logger.warning("_loop_training: population has no evolve() method.")
                break

        self._release_all_keys()
        logger.debug("_loop_training: thread exited.")

    # ==================================================================
    # Decision tick
    # ==================================================================
    def _tick(self, brain) -> None:
        """Single decision tick: read state → think → act."""
        # 1. Read game state
        if self.state_reader is not None:
            try:
                state = self.state_reader.read_state()
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug("_tick: state_reader.read_state() failed: %s", exc)
                state = dict(self._DUMMY_STATE)
        else:
            state = dict(self._DUMMY_STATE)

        # 2. Build input vector (order must match what NEAT was trained with)
        inputs = [
            state.get("car_angle",        0.0),
            state.get("angular_velocity",  0.0),
            state.get("on_ground",         1.0),
            state.get("terrain_height",    0.0),
            state.get("terrain_slope",     0.0),
            state.get("fuel",              0.0),
        ]

        # 3. Think
        try:
            decision = brain.think(inputs)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("_tick: brain.think() failed: %s", exc)
            decision = [0.0, 0.0]

        # 4. Store decision for UI
        with self._lock:
            self._last_decision = list(decision)

        # 5. Act
        self._apply_decision(decision)

    # ==================================================================
    # Key control
    # ==================================================================
    def _apply_decision(self, decision: list) -> None:
        """
        decision[0] > 0.5 → press GAS_KEY (right arrow)
        decision[1] > 0.5 → press BRAKE_KEY (left arrow)
        Release any key that is no longer active.
        """
        if not _KEYBOARD_AVAILABLE or keyboard is None:
            return

        try:
            gas_active   = len(decision) > 0 and decision[0] > 0.5
            brake_active = len(decision) > 1 and decision[1] > 0.5

            # Gas key
            if gas_active and self.GAS_KEY not in self._keys_pressed:
                keyboard.press(self.GAS_KEY)
                self._keys_pressed.add(self.GAS_KEY)
            elif not gas_active and self.GAS_KEY in self._keys_pressed:
                keyboard.release(self.GAS_KEY)
                self._keys_pressed.discard(self.GAS_KEY)

            # Brake key
            if brake_active and self.BRAKE_KEY not in self._keys_pressed:
                keyboard.press(self.BRAKE_KEY)
                self._keys_pressed.add(self.BRAKE_KEY)
            elif not brake_active and self.BRAKE_KEY in self._keys_pressed:
                keyboard.release(self.BRAKE_KEY)
                self._keys_pressed.discard(self.BRAKE_KEY)

        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("_apply_decision: key press error: %s", exc)

    def _release_all_keys(self) -> None:
        """Release GAS and BRAKE keys safely."""
        if not _KEYBOARD_AVAILABLE or keyboard is None:
            self._keys_pressed.clear()
            return

        for key in (self.GAS_KEY, self.BRAKE_KEY):
            try:
                keyboard.release(key)
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug("_release_all_keys: could not release '%s': %s", key, exc)

        self._keys_pressed.clear()

    # ==================================================================
    # Thread-safe properties
    # ==================================================================
    @property
    def generation(self) -> int:
        with self._lock:
            return self._gen

    @property
    def best_score(self) -> float:
        with self._lock:
            return self._best_score

    @property
    def current_score(self) -> float:
        with self._lock:
            return self._current_score

    @property
    def species_count(self) -> int:
        with self._lock:
            return self._species_count

    @property
    def last_decision(self) -> list:
        with self._lock:
            return list(self._last_decision)

    # ==================================================================
    # Brain persistence
    # ==================================================================
    def save_brain(self, path: str = "best_brain.json") -> None:
        """Save best brain to JSON."""
        brain = getattr(self, "_best_brain_ref", None) or self.brain
        if brain is None:
            logger.warning("save_brain: no brain to save.")
            return

        try:
            if hasattr(brain, "save"):
                brain.save(path)
                logger.info("save_brain: brain saved to '%s' via brain.save().", path)
            else:
                import json
                data = brain.__dict__ if hasattr(brain, "__dict__") else {}
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2)
                logger.info("save_brain: brain saved to '%s' via JSON dump.", path)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("save_brain: failed — %s", exc)

    def load_brain(self, path: str = "best_brain.json") -> bool:
        """Load brain from JSON. Returns True on success."""
        if not os.path.isfile(path):
            logger.warning("load_brain: file not found — '%s'.", path)
            return False

        try:
            if _NEAT_AVAILABLE and NEATBrain is not None:
                brain = NEATBrain.load(path) if hasattr(NEATBrain, "load") else NEATBrain()
                if hasattr(brain, "load"):
                    brain.load(path)
                self.brain = brain
                logger.info("load_brain: NEATBrain loaded from '%s'.", path)
                return True

            # Fallback: load raw JSON dict
            import json
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            logger.info("load_brain: JSON data loaded from '%s' (no NEATBrain class).", path)
            self.brain = data  # caller must handle dict brain
            return True

        except Exception as exc:  # pylint: disable=broad-except
            logger.error("load_brain: failed — %s", exc)
            return False

    # ==================================================================
    # Internal helpers
    # ==================================================================
    def _reset_stop_event(self) -> None:
        """Clear the stop event so a new loop can start."""
        self._stop_event.clear()


# ===========================================================================
# Quick smoke-test
# ===========================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("AI Controller ready")
    print("=" * 60)
    print(f"  keyboard available : {_KEYBOARD_AVAILABLE}")
    print(f"  pymem    available : {_PYMEM_AVAILABLE}")
    print(f"  neat_brain available: {_NEAT_AVAILABLE}")
    print()

    ctrl = AIController()
    print(f"  tick_interval      : {ctrl.tick_interval} s  ({1/ctrl.tick_interval:.0f} Hz)")
    print(f"  GAS_KEY            : {ctrl.GAS_KEY!r}")
    print(f"  BRAKE_KEY          : {ctrl.BRAKE_KEY!r}")
    print()

    # Demonstrate GameStateReader with no game attached
    reader = GameStateReader(pm=None, base_address=0, module_base=0)
    state  = reader.read_state()
    print("  Dummy state_reader.read_state():")
    for k, v in state.items():
        print(f"    {k:20s} = {v}")
    print()
    print("All OK — ready to integrate with trainer UI.")
