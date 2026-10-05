# Copyright (c) 2026 Robert Bosch GmbH
# SPDX-License-Identifier: AGPL-3.0

# This source code is derived from PufferDrive V2.0
# (https://github.com/Emerge-Lab/PufferDrive, version 1d864db)
# Copyright (c) PufferDrive authors, licensed under the MIT license,
# cf. 3rd-party-licenses.txt file in the root directory of this source tree.

import numpy as np
import gymnasium
import json
import struct
import os
import pufferlib
from pathlib import Path
from pufferlib.ocean.drive import binding
from multiprocessing import Pool, cpu_count
from tqdm import tqdm

_DRIVE_INI = str(Path(__file__).parent.parent.parent / "config" / "ocean" / "drive.ini")


class Drive(pufferlib.PufferEnv):
    def __init__(
        self,
        data_root=None,
        split="training",
        render_mode=None,
        report_interval=1,
        width=1280,
        height=1024,
        human_agent_idx=0,
        reward_vehicle_collision=-0.1,
        reward_offroad_collision=-0.1,
        reward_goal=1.0,
        reward_goal_post_respawn=0.5,
        goal_behavior=0,
        goal_target_distance=10.0,
        goal_radius=2.0,
        goal_speed=20.0,
        collision_behavior=0,
        offroad_behavior=0,
        dt=0.1,
        episode_length=None,
        termination_mode=None,
        resample_frequency=91,
        num_maps=100,
        num_agents=512,
        action_type="discrete",
        dynamics_model="classic",
        max_controlled_agents=-1,
        buf=None,
        seed=1,
        init_steps=0,
        init_mode="create_all_valid",
        control_mode="control_vehicles",
        #map_dir="resources/drive/binaries/training",
        use_all_maps=False,
        map_id=None,
    ):
        # env
        self.dt = dt
        self.render_mode = render_mode
        self.num_maps = num_maps
        self.report_interval = report_interval
        self.reward_vehicle_collision = reward_vehicle_collision
        self.reward_offroad_collision = reward_offroad_collision
        self.reward_goal = reward_goal
        self.reward_goal_post_respawn = reward_goal_post_respawn
        self.goal_radius = goal_radius
        self.goal_speed = goal_speed
        self.goal_behavior = goal_behavior
        self.goal_target_distance = goal_target_distance
        self.collision_behavior = collision_behavior
        self.offroad_behavior = offroad_behavior
        self.human_agent_idx = human_agent_idx
        self.episode_length = episode_length
        self.termination_mode = termination_mode
        self.resample_frequency = resample_frequency
        self.dynamics_model = dynamics_model

        # Observation space calculation
        self.ego_features = {"classic": binding.EGO_FEATURES_CLASSIC, "jerk": binding.EGO_FEATURES_JERK}.get(
            dynamics_model
        )

        # Extract observation shapes from constants
        # These need to be defined in C, since they determine the shape of the arrays
        self.max_road_objects = binding.MAX_ROAD_SEGMENT_OBSERVATIONS
        self.max_partner_objects = binding.MAX_AGENTS - 1
        self.partner_features = binding.PARTNER_FEATURES
        self.road_features = binding.ROAD_FEATURES

        self.num_obs = (
            self.ego_features
            + self.max_partner_objects * self.partner_features
            + self.max_road_objects * self.road_features
        )
        self.single_observation_space = gymnasium.spaces.Box(low=-1, high=1, shape=(self.num_obs,), dtype=np.float32)
        
        if data_root == None:
            if 'DRIVE_BINARIES_DATA_ROOT' in os.environ:
                data_root = os.environ['DRIVE_BINARIES_DATA_ROOT']
            else:
                raise ValueError(f"data_root is not specified and environment variable DRIVE_BINARIES_DATA_ROOT is not set")
        self.init_steps = init_steps
        self.init_mode_str = init_mode
        self.control_mode_str = control_mode
        #self.map_dir = map_dir

        if self.control_mode_str == "control_vehicles":
            self.control_mode = 0
        elif self.control_mode_str == "control_agents":
            self.control_mode = 1
        elif self.control_mode_str == "control_wosac":
            self.control_mode = 2
        elif self.control_mode_str == "control_sdc_only":
            self.control_mode = 3
        else:
            raise ValueError(
                f"control_mode must be one of 'control_vehicles', 'control_wosac', or 'control_agents'. Got: {self.control_mode_str}"
            )
        if self.init_mode_str == "create_all_valid":
            self.init_mode = 0
        elif self.init_mode_str == "create_only_controlled":
            self.init_mode = 1
        else:
            raise ValueError(
                f"init_mode must be one of 'create_all_valid' or 'create_only_controlled'. Got: {self.init_mode_str}"
            )

        
        self.data_root = data_root

        assert split in ["training", "validation", "testing"], f"Passed parameter 'split' must be 'training', 'validation' or 'testing'. Got: {split}"

        self.split = split

        
        if action_type == "discrete":
            if dynamics_model == "classic":
                # Joint action space (assume dependence)
                self.single_action_space = gymnasium.spaces.MultiDiscrete([7 * 13])
                # Multi discrete (assume independence)
                # self.single_action_space = gymnasium.spaces.MultiDiscrete([7, 13])
            elif dynamics_model == "jerk":
                # Joint action space (assume dependence) - 4 longitudinal × 3 lateral = 12
                self.single_action_space = gymnasium.spaces.MultiDiscrete([4 * 3])
            else:
                raise ValueError(f"dynamics_model must be 'classic' or 'jerk'. Got: {dynamics_model}")
        elif action_type == "continuous":
            self.single_action_space = gymnasium.spaces.Box(low=-1, high=1, shape=(2,), dtype=np.float32)
        else:
            raise ValueError(f"action_space must be 'discrete' or 'continuous'. Got: {action_type}")

        self._action_type_flag = 0 if action_type == "discrete" else 1

        # Check if resources directory exists
        # binary_path = "resources/drive/binaries/map_000.bin"
        binary_path = os.path.join(data_root, split, "map_000000.bin")
        if not os.path.exists(binary_path):
            raise FileNotFoundError(
                f"Required directory {binary_path} not found. Please ensure the Drive maps are downloaded and installed correctly per docs."
            )

        # Check maps availability
        # available_maps = len([name for name in os.listdir("resources/drive/binaries") if name.endswith(".bin")])
        available_maps = len([name for name in os.listdir(os.path.join(data_root, split)) if name.endswith(".bin")])
        if num_maps > available_maps:
            raise ValueError(
                f"num_maps ({num_maps}) exceeds available maps in directory ({available_maps}). Please reduce num_maps or add more maps to resources/drive/binaries."
            )
        self.max_controlled_agents = int(max_controlled_agents)

        if map_id is not None:
            # Single-map viewer mode: skip binding.shared() and pin to the requested map.
            agent_offsets = [0, num_agents]
            map_ids = [map_id]
            num_envs = 1
        else:
            # Iterate through all maps to count total agents that can be initialized for each map
            agent_offsets, map_ids, num_envs = binding.shared(
                #map_dir=map_dir,
                num_agents=num_agents,
                num_maps=num_maps,
                split=split,
                data_root=data_root,
                init_mode=self.init_mode,
                control_mode=self.control_mode,
                init_steps=self.init_steps,
                max_controlled_agents=self.max_controlled_agents,
                goal_behavior=self.goal_behavior,
                goal_target_distance=self.goal_target_distance,
                use_all_maps=use_all_maps,
            )

        # agent_offsets[-1] works in both cases, just making it explicit that num_agents is ignored if use_all_maps
        self.num_agents = num_agents if not use_all_maps else agent_offsets[-1]
        self.agent_offsets = agent_offsets
        self.map_ids = map_ids
        self.num_envs = num_envs
        super().__init__(buf=buf)
        env_ids = []
        for i in range(num_envs):
            cur = agent_offsets[i]
            nxt = agent_offsets[i + 1]
            env_id = binding.env_init(
                self.observations[cur:nxt],
                self.actions[cur:nxt],
                self.rewards[cur:nxt],
                self.terminals[cur:nxt],
                self.truncations[cur:nxt],
                seed,
                action_type=self._action_type_flag,
                human_agent_idx=human_agent_idx,
                reward_vehicle_collision=reward_vehicle_collision,
                reward_offroad_collision=reward_offroad_collision,
                reward_goal=reward_goal,
                reward_goal_post_respawn=reward_goal_post_respawn,
                goal_radius=goal_radius,
                goal_speed=goal_speed,
                goal_behavior=self.goal_behavior,
                goal_target_distance=self.goal_target_distance,
                collision_behavior=self.collision_behavior,
                offroad_behavior=self.offroad_behavior,
                dt=dt,
                episode_length=(int(episode_length) if episode_length is not None else None),
                termination_mode=(int(self.termination_mode) if self.termination_mode is not None else 0),
                max_controlled_agents=self.max_controlled_agents,
                map_id=map_ids[i],
                max_agents=nxt - cur,
                ini_file=_DRIVE_INI,
                init_steps=init_steps,
                init_mode=self.init_mode,
                control_mode=self.control_mode,

                data_root=self.data_root,
                split=split,

                #map_dir=self.map_dir,

            )
            env_ids.append(env_id)

        self.c_envs = binding.vectorize(*env_ids)

    def reset(self, seed=0):
        binding.vec_reset(self.c_envs, seed)
        self.tick = 0
        return self.observations, []

    def step(self, actions):
        
        self.terminals[:] = 0
        self.truncations[:] = 0
        self.actions[:] = actions
        # reset environment, if resample_frequency is reached, you do not need to step in this case!
        if self.tick > 0 and self.resample_frequency > 0 and self.tick % self.resample_frequency == 0:
            self.tick = 0
            binding.vec_close(self.c_envs)
            agent_offsets, map_ids, num_envs = binding.shared(
                num_agents=self.num_agents,
                num_maps=self.num_maps,
                init_mode=self.init_mode,
                control_mode=self.control_mode,
                init_steps=self.init_steps,
                max_controlled_agents=self.max_controlled_agents,
                goal_behavior=self.goal_behavior,
                goal_target_distance=self.goal_target_distance,
                goal_speed=self.goal_speed,
                split=self.split, 
                data_root=self.data_root,

                #map_dir=self.map_dir,
                use_all_maps=False,
            )
            self.agent_offsets = agent_offsets
            self.map_ids = map_ids
            self.num_envs = num_envs
            env_ids = []
            seed = np.random.randint(0, 2**32 - 1)
            for i in range(num_envs):
                cur = agent_offsets[i]
                nxt = agent_offsets[i + 1]
                env_id = binding.env_init(
                    self.observations[cur:nxt],
                    self.actions[cur:nxt],
                    self.rewards[cur:nxt],
                    self.terminals[cur:nxt],
                    self.truncations[cur:nxt],
                    seed,
                    action_type=self._action_type_flag,
                    human_agent_idx=self.human_agent_idx,
                    reward_vehicle_collision=self.reward_vehicle_collision,
                    reward_offroad_collision=self.reward_offroad_collision,
                    reward_goal=self.reward_goal,
                    reward_goal_post_respawn=self.reward_goal_post_respawn,
                    goal_radius=self.goal_radius,
                    goal_behavior=self.goal_behavior,
                    goal_target_distance=self.goal_target_distance,
                    goal_speed=self.goal_speed,
                    collision_behavior=self.collision_behavior,
                    offroad_behavior=self.offroad_behavior,
                    dt=self.dt,
                    episode_length=(int(self.episode_length) if self.episode_length is not None else None),
                    max_controlled_agents=self.max_controlled_agents,
                    map_id=map_ids[i],
                    max_agents=nxt - cur,
                    ini_file=_DRIVE_INI,
                    init_steps=self.init_steps,
                    init_mode=self.init_mode,
                    control_mode=self.control_mode,
                    data_root=self.data_root,
                    split=self.split,

                    #map_dir=self.map_dir,
                )
                env_ids.append(env_id)
            self.c_envs = binding.vectorize(*env_ids)

            binding.vec_reset(self.c_envs, seed)
            info = []
        
        else:
            binding.vec_step(self.c_envs) # truncations and terminals get set in here as well.
            self.tick += 1
            info = []
            if self.tick % self.report_interval == 0:
                log = binding.vec_log(self.c_envs, self.num_agents)
                if log:
                    info.append(log)
                    # print(log)
            if self.tick > 0 and self.resample_frequency > 0 and self.tick % self.resample_frequency == 0: # self.tick just got increased!
                self.truncations[:] = 1.0 # truncations are the ones which are after time out right??

            

        return (self.observations, self.rewards, self.terminals, self.truncations, info)

    def set_goals(self, goal_changes: dict):
        """Set goal positions for agents.

        Args:
            goal_changes: {entity_idx: (goal_x, goal_y)} in world coordinates
        """
        binding.vec_set_goals(self.c_envs, goal_changes=goal_changes)
        binding.vec_recompute_observations(self.c_envs)

    def get_global_agent_state(self):
        """Get current global state of all active agents.

        Returns:
            dict with keys 'x', 'y', 'z', 'heading', 'id', 'length', 'width' containing numpy arrays
            of shape (num_active_agents,)
        """
        num_agents = self.num_agents

        states = {
            "x": np.zeros(num_agents, dtype=np.float32),
            "y": np.zeros(num_agents, dtype=np.float32),
            "z": np.zeros(num_agents, dtype=np.float32),
            "heading": np.zeros(num_agents, dtype=np.float32),
            "id": np.zeros(num_agents, dtype=np.int32),
            "length": np.zeros(num_agents, dtype=np.float32),
            "width": np.zeros(num_agents, dtype=np.float32),
        }

        binding.vec_get_global_agent_state(
            self.c_envs,
            states["x"],
            states["y"],
            states["z"],
            states["heading"],
            states["id"],
            states["length"],
            states["width"],
        )

        return states

    def get_active_agent_count(self) -> int:
        return binding.vec_get_active_agent_count(self.c_envs)

    def inject_active_agent(self, x: float, y: float, heading: float,
                            goal_x: float, goal_y: float, env_idx: int = 0) -> bool:
        """Hijack an inactive vehicle slot to add a new policy-controlled agent.

        Call after reset() and before the first step(). Returns True on success.
        The injection is discarded on the next reset().
        """
        rc = binding.vec_inject_active_agent(
            self.c_envs, x=float(x), y=float(y), heading=float(heading),
            goal_x=float(goal_x), goal_y=float(goal_y), env_idx=int(env_idx),
        )
        return rc == 1

    def inject_static_agent(self, x: float, y: float, heading: float, env_idx: int = 0) -> bool:
        """Place a non-moving vehicle at the given world position and heading.

        Call after reset() and before the first step(). Returns True on success.
        """
        rc = binding.vec_inject_static_agent(
            self.c_envs, x=float(x), y=float(y), heading=float(heading), env_idx=int(env_idx),
        )
        return rc == 1

    def teleport_agent(self, active_slot: int, x: float, y: float,
                       heading: float, goal_x: float, goal_y: float):
        binding.vec_teleport_agent(self.c_envs, 0, active_slot,
                                   float(x), float(y), float(heading),
                                   float(goal_x), float(goal_y))

    def teleport_static_agent(self, nonexpert_idx: int, x: float, y: float,
                              heading: float, env_idx: int = 0):
        """Reposition a non-expert static agent in place, keeping its slot/identity.
        nonexpert_idx is the index in the non-expert static order (matches
        get_static_agent_state / detach_static_agent)."""
        binding.vec_teleport_static_agent(self.c_envs, int(env_idx), int(nonexpert_idx),
                                          float(x), float(y), float(heading))

    def teleport_expert_agent(self, expert_idx: int, world_xs, world_ys, headings, env_idx: int = 0):
        """Reposition an expert agent in place by replacing its trajectory, keeping its slot.
        expert_idx is the index in the expert order (matches detach_expert_agent)."""
        import numpy as np
        xs = np.asarray(world_xs, dtype=np.float32)
        ys = np.asarray(world_ys, dtype=np.float32)
        hs = np.asarray(headings, dtype=np.float32)
        binding.vec_teleport_expert_agent(
            self.c_envs, expert_idx=int(expert_idx), xs=xs, ys=ys, headings=hs, env_idx=int(env_idx),
        )

    def reset_injections(self):
        """Restore agent counts to original post-init values before re-injecting."""
        binding.vec_reset_injections(self.c_envs)

    def prepare_reserved_slots(self):
        """Pre-park N spare vehicles at (-9000,-9000) to guarantee injection slots exist."""
        binding.vec_prepare_reserved_slots(self.c_envs)

    def detach_active_agent(self, slot_idx: int, env_idx: int = 0):
        """Remove an active agent from the pool (frees a slot for demo injection in full scenes).
        Pass slot indices in descending order when calling multiple times."""
        binding.vec_detach_active_agent(self.c_envs, int(env_idx), int(slot_idx))

    def detach_static_agent(self, slot_idx: int, env_idx: int = 0):
        """Remove a non-expert static agent from the pool (frees a slot for demo injection).
        Pass slot indices in descending order when calling multiple times."""
        binding.vec_detach_static_agent(self.c_envs, int(env_idx), int(slot_idx))

    def detach_expert_agent(self, slot_idx: int, env_idx: int = 0):
        """Remove an expert static agent from the pool (frees a slot for demo injection).
        Pass slot indices in descending order when calling multiple times."""
        binding.vec_detach_expert_agent(self.c_envs, int(env_idx), int(slot_idx))

    def prepare_demo_slots(self):
        """Allocate 10 ghost active + 10 ghost static demo slots permanently at INVALID_POSITION."""
        binding.vec_prepare_demo_slots(self.c_envs)

    def reset_demo_slots(self):
        """Park all demo slots back to INVALID_POSITION before re-injecting user agents."""
        binding.vec_reset_demo_slots(self.c_envs)

    def inject_demo_active_agent(self, x: float, y: float, heading: float,
                                  goal_x: float, goal_y: float, env_idx: int = 0,
                                  length: float = 0.0, width: float = 0.0) -> int:
        """Place a user dynamic agent in the first free demo active slot. Returns slot index or -1."""
        return binding.vec_inject_demo_active_agent(
            self.c_envs, x=float(x), y=float(y), heading=float(heading),
            goal_x=float(goal_x), goal_y=float(goal_y), env_idx=int(env_idx),
            length=float(length), width=float(width),
        )

    def inject_demo_static_agent(self, x: float, y: float, heading: float, env_idx: int = 0,
                                  length: float = 0.0, width: float = 0.0) -> int:
        """Place a user static agent in the first free demo static slot. Returns slot index or -1."""
        return binding.vec_inject_demo_static_agent(
            self.c_envs, x=float(x), y=float(y), heading=float(heading), env_idx=int(env_idx),
            length=float(length), width=float(width),
        )

    def inject_demo_expert_agent(self, x: float, y: float, heading: float, env_idx: int = 0,
                                  length: float = 0.0, width: float = 0.0) -> int:
        """Place a user expert agent in the first free demo expert slot. Returns slot_k or -1."""
        return binding.vec_inject_demo_expert_agent(
            self.c_envs, x=float(x), y=float(y), heading=float(heading), env_idx=int(env_idx),
            length=float(length), width=float(width),
        )

    def set_demo_expert_trajectory(self, slot_k: int, world_xs, world_ys, headings, env_idx: int = 0):
        """Write a full trajectory into a demo expert slot. Arrays must be float32 numpy arrays."""
        import numpy as np
        xs = np.asarray(world_xs, dtype=np.float32)
        ys = np.asarray(world_ys, dtype=np.float32)
        hs = np.asarray(headings, dtype=np.float32)
        binding.vec_set_demo_expert_traj(
            self.c_envs, slot_k=int(slot_k), xs=xs, ys=ys, headings=hs, env_idx=int(env_idx),
        )

    def get_demo_slots_info(self, env_idx: int = 0) -> tuple[int, int]:
        """Returns (used, total) for the shared demo slot pool."""
        return binding.vec_get_demo_slots_info(self.c_envs, env_idx=int(env_idx))

    def recompute_observations(self):
        binding.vec_recompute_observations(self.c_envs)

    def get_expert_agent_state(self):
        """Get current state of expert (non-controlled) agents."""
        n = binding.vec_get_expert_agent_count(self.c_envs)
        if n == 0:
            return {"x": np.zeros(0, dtype=np.float32), "y": np.zeros(0, dtype=np.float32),
                    "heading": np.zeros(0, dtype=np.float32), "length": np.zeros(0, dtype=np.float32),
                    "width": np.zeros(0, dtype=np.float32)}
        states = {
            "x":       np.zeros(n, dtype=np.float32),
            "y":       np.zeros(n, dtype=np.float32),
            "heading": np.zeros(n, dtype=np.float32),
            "length":  np.zeros(n, dtype=np.float32),
            "width":   np.zeros(n, dtype=np.float32),
        }
        binding.vec_get_expert_agent_state(self.c_envs, states["x"], states["y"],
                                           states["heading"], states["length"], states["width"])
        return states

    def get_agent_statuses(self) -> np.ndarray:
        """Return per-agent status codes as int32 array of shape (num_agents,).

        Status codes (also exported as AGENT_STATUS_* constants in binding):
          0 = Running      — active and moving
          1 = Paused       — stopped (stopped=1, not removed)
          2 = Crashed      — removed due to vehicle collision
          3 = Offroad      — removed due to offroad collision
          4 = Goal reached — current_goal_reached=1

        Must be called immediately after env.step() for Crashed/Offroad to be
        distinguishable — the underlying metrics reset at the start of the next step.
        """
        statuses = np.zeros(self.num_agents, dtype=np.int32)
        binding.vec_get_agent_statuses(self.c_envs, statuses)
        return statuses

    def get_static_agent_state(self):
        """Get initial state of static (parked) vehicles — non-controlled, non-expert agents."""
        n = binding.vec_get_static_agent_count(self.c_envs)
        if n == 0:
            return {"x": np.zeros(0, dtype=np.float32), "y": np.zeros(0, dtype=np.float32),
                    "heading": np.zeros(0, dtype=np.float32), "length": np.zeros(0, dtype=np.float32),
                    "width": np.zeros(0, dtype=np.float32)}
        states = {
            "x":       np.zeros(n, dtype=np.float32),
            "y":       np.zeros(n, dtype=np.float32),
            "heading": np.zeros(n, dtype=np.float32),
            "length":  np.zeros(n, dtype=np.float32),
            "width":   np.zeros(n, dtype=np.float32),
        }
        binding.vec_get_static_agent_state(self.c_envs, states["x"], states["y"],
                                           states["heading"], states["length"], states["width"])
        return states

    def get_ground_truth_trajectories(self):
        """Get ground truth trajectories for all active agents.

        Returns:
            dict with keys 'x', 'y', 'z', 'heading', 'valid', 'id', 'scenario_id' containing numpy arrays.
        """
        num_agents = self.num_agents

        trajectories = {
            "x": np.zeros((num_agents, self.episode_length - self.init_steps), dtype=np.float32),
            "y": np.zeros((num_agents, self.episode_length - self.init_steps), dtype=np.float32),
            "z": np.zeros((num_agents, self.episode_length - self.init_steps), dtype=np.float32),
            "heading": np.zeros((num_agents, self.episode_length - self.init_steps), dtype=np.float32),
            "valid": np.zeros((num_agents, self.episode_length - self.init_steps), dtype=np.int32),
            "id": np.zeros(num_agents, dtype=np.int32),
            "scenario_id": np.zeros(num_agents, dtype=np.int32),
        }

        binding.vec_get_global_ground_truth_trajectories(
            self.c_envs,
            trajectories["x"],
            trajectories["y"],
            trajectories["z"],
            trajectories["heading"],
            trajectories["valid"],
            trajectories["id"],
            trajectories["scenario_id"],
        )

        for key in trajectories:
            trajectories[key] = trajectories[key][:, None]

        return trajectories

    def get_road_edge_polylines(self):
        """Get road edge polylines for all scenarios.

        Returns:
            dict with keys 'x', 'y', 'lengths', 'scenario_id' containing numpy arrays.
            x, y are flattened point coordinates; lengths indicates points per polyline.
        """
        num_polylines, total_points = binding.vec_get_road_edge_counts(self.c_envs)

        polylines = {
            "x": np.zeros(total_points, dtype=np.float32),
            "y": np.zeros(total_points, dtype=np.float32),
            "lengths": np.zeros(num_polylines, dtype=np.int32),
            "scenario_id": np.zeros(num_polylines, dtype=np.int32),
        }

        binding.vec_get_road_edge_polylines(
            self.c_envs,
            polylines["x"],
            polylines["y"],
            polylines["lengths"],
            polylines["scenario_id"],
        )

        return polylines

    def get_lane_polylines(self):
        """Get road lane polylines for all scenarios.

        Returns:
            dict with keys 'x', 'y', 'lengths', 'scenario_id' containing numpy arrays.
            x, y are flattened point coordinates; lengths indicates points per polyline.
        """
        num_polylines, total_points = binding.vec_get_lane_counts(self.c_envs)

        polylines = {
            "x": np.zeros(total_points, dtype=np.float32),
            "y": np.zeros(total_points, dtype=np.float32),
            "lengths": np.zeros(num_polylines, dtype=np.int32),
            "scenario_id": np.zeros(num_polylines, dtype=np.int32),
        }

        binding.vec_get_lane_polylines(
            self.c_envs,
            polylines["x"],
            polylines["y"],
            polylines["lengths"],
            polylines["scenario_id"],
        )

        return polylines

    def render(self):
        binding.vec_render(self.c_envs, 0)

    def close(self):
        binding.vec_close(self.c_envs)


def calculate_area(p1, p2, p3):
    # Calculate the area of the triangle using the determinant method
    return 0.5 * abs((p1["x"] - p3["x"]) * (p2["y"] - p1["y"]) - (p1["x"] - p2["x"]) * (p3["y"] - p1["y"]))


def dist(a, b):
    dx = a["x"] - b["x"]
    dy = a["y"] - b["y"]
    return dx * dx + dy * dy


def simplify_polyline(geometry, polyline_reduction_threshold, max_segment_length):
    """Simplify the given polyline using a method inspired by Visvalingham-Whyatt, optimized for Python."""
    num_points = len(geometry)
    if num_points < 3:
        return geometry  # Not enough points to simplify

    skip = [False] * num_points
    skip_changed = True

    while skip_changed:
        skip_changed = False
        k = 0
        while k < num_points - 1:
            k_1 = k + 1
            while k_1 < num_points - 1 and skip[k_1]:
                k_1 += 1
            if k_1 >= num_points - 1:
                break

            k_2 = k_1 + 1
            while k_2 < num_points and skip[k_2]:
                k_2 += 1
            if k_2 >= num_points:
                break

            point1 = geometry[k]
            point2 = geometry[k_1]
            point3 = geometry[k_2]
            area = calculate_area(point1, point2, point3)
            if area < polyline_reduction_threshold and dist(point1, point3) <= max_segment_length:
                skip[k_1] = True
                skip_changed = True
                k = k_2
            else:
                k = k_1

    return [geometry[i] for i in range(num_points) if not skip[i]]


def save_map_binary(map_data, output_file, unique_map_id):
    trajectory_length = 91
    """Saves map data in a binary format readable by C"""
    with open(output_file, "wb") as f:
        # Get metadata
        metadata = map_data.get("metadata", {})
        sdc_track_index = metadata.get("sdc_track_index", -1)  # -1 as default if not found
        tracks_to_predict = metadata.get("tracks_to_predict", [])

        # Write sdc_track_index
        f.write(struct.pack("i", sdc_track_index))

        # Write tracks_to_predict info (indices only)
        f.write(struct.pack("i", len(tracks_to_predict)))
        for track in tracks_to_predict:
            track_index = track.get("track_index", -1)
            f.write(struct.pack("i", track_index))

        # Count total entities
        num_objects = len(map_data.get("objects", []))
        num_roads = len(map_data.get("roads", []))
        # num_entities = num_objects + num_roads
        f.write(struct.pack("i", num_objects))
        f.write(struct.pack("i", num_roads))
        # f.write(struct.pack('i', num_entities))
        # Write objects
        for obj in map_data.get("objects", []):
            # Write unique map id
            f.write(struct.pack("i", unique_map_id))

            # Write base entity data
            obj_type = obj.get("type", 1)
            if obj_type == "vehicle":
                obj_type = 1
            elif obj_type == "pedestrian":
                obj_type = 2
            elif obj_type == "cyclist":
                obj_type = 3
            f.write(struct.pack("i", obj_type))  # type
            f.write(struct.pack("i", obj.get("id", 0)))  # id
            f.write(struct.pack("i", trajectory_length))  # array_size
            # Write position arrays
            positions = obj.get("position", [])
            for i in range(trajectory_length):
                pos = positions[i] if i < len(positions) else {"x": 0.0, "y": 0.0, "z": 0.0}
                f.write(struct.pack("f", float(pos.get("x", 0.0))))
            for i in range(trajectory_length):
                pos = positions[i] if i < len(positions) else {"x": 0.0, "y": 0.0, "z": 0.0}
                f.write(struct.pack("f", float(pos.get("y", 0.0))))
            for i in range(trajectory_length):
                pos = positions[i] if i < len(positions) else {"x": 0.0, "y": 0.0, "z": 0.0}
                f.write(struct.pack("f", float(pos.get("z", 0.0))))

            # Write velocity arrays
            velocities = obj.get("velocity", [])
            for arr, key in [(velocities, "x"), (velocities, "y"), (velocities, "z")]:
                for i in range(trajectory_length):
                    vel = arr[i] if i < len(arr) else {"x": 0.0, "y": 0.0, "z": 0.0}
                    f.write(struct.pack("f", float(vel.get(key, 0.0))))

            # Write heading and valid arrays
            headings = obj.get("heading", [])
            f.write(
                struct.pack(
                    f"{trajectory_length}f",
                    *[float(headings[i]) if i < len(headings) else 0.0 for i in range(trajectory_length)],
                )
            )

            valids = obj.get("valid", [])
            f.write(
                struct.pack(
                    f"{trajectory_length}i",
                    *[int(valids[i]) if i < len(valids) else 0 for i in range(trajectory_length)],
                )
            )

            # Write scalar fields
            f.write(struct.pack("f", float(obj.get("width", 0.0))))
            f.write(struct.pack("f", float(obj.get("length", 0.0))))
            f.write(struct.pack("f", float(obj.get("height", 0.0))))
            goal_pos = obj.get("goalPosition", {"x": 0, "y": 0, "z": 0})  # Get goalPosition object with default
            f.write(struct.pack("f", float(goal_pos.get("x", 0.0))))  # Get x value
            f.write(struct.pack("f", float(goal_pos.get("y", 0.0))))  # Get y value
            f.write(struct.pack("f", float(goal_pos.get("z", 0.0))))  # Get z value
            f.write(struct.pack("i", obj.get("mark_as_expert", 0)))

        # Write roads
        for idx, road in enumerate(map_data.get("roads", [])):
            f.write(struct.pack("i", unique_map_id))

            geometry = road.get("geometry", [])
            road_type = road.get("map_element_id", 0)
            road_type_word = road.get("type", 0)
            if road_type_word == "lane":
                road_type = 2
            elif road_type_word == "road_edge":
                road_type = 15
            # breakpoint()
            if len(geometry) > 10 and road_type <= 16:
                geometry = simplify_polyline(geometry, 0.1, 250)
            size = len(geometry)
            # breakpoint()
            if road_type >= 0 and road_type <= 3:
                road_type = 4
            elif road_type >= 5 and road_type <= 13:
                road_type = 5
            elif road_type >= 14 and road_type <= 16:
                road_type = 6
            elif road_type == 17:
                road_type = 7
            elif road_type == 18:
                road_type = 8
            elif road_type == 19:
                road_type = 9
            elif road_type == 20:
                road_type = 10
            # Write base entity data
            f.write(struct.pack("i", road_type))  # type
            f.write(struct.pack("i", road.get("id", 0)))  # id
            f.write(struct.pack("i", size))  # array_size

            # Write position arrays
            for coord in ["x", "y", "z"]:
                for point in geometry:
                    f.write(struct.pack("f", float(point.get(coord, 0.0))))

            # Write scalar fields
            f.write(struct.pack("f", float(road.get("width", 0.0))))
            f.write(struct.pack("f", float(road.get("length", 0.0))))
            f.write(struct.pack("f", float(road.get("height", 0.0))))
            goal_pos = road.get("goalPosition", {"x": 0, "y": 0, "z": 0})  # Get goalPosition object with default
            f.write(struct.pack("f", float(goal_pos.get("x", 0.0))))  # Get x value
            f.write(struct.pack("f", float(goal_pos.get("y", 0.0))))  # Get y value
            f.write(struct.pack("f", float(goal_pos.get("z", 0.0))))  # Get z value
            f.write(struct.pack("i", road.get("mark_as_expert", 0)))


def load_map(map_name, unique_map_id, binary_output=None):
    """Loads a JSON map and optionally saves it as binary"""
    with open(map_name, "r") as f:
        map_data = json.load(f)

    if binary_output:
        save_map_binary(map_data, binary_output, unique_map_id)


def _process_single_map(args):
    """Worker function to process a single map file"""
    i, map_path, binary_path = args
    try:
        load_map(str(map_path), i, str(binary_path))
        return (i, map_path.name, True, None)
    except Exception as e:
        return (i, map_path.name, False, str(e))


def process_all_maps(
    json_dir, 
    binary_dir,
    max_maps=10_000,
    num_workers=None,
):
    """Process all maps and save them as binaries using multiprocessing

    Args:
        data_folder: Path to the folder containing JSON map files
        max_maps: Maximum number of maps to process
        num_workers: Number of parallel workers (defaults to cpu_count())
    """
    from pathlib import Path

    # Create the binaries directory if it doesn't exist
    # binary_dir = Path("resources/drive/binaries")
    binary_dir.mkdir(parents=True, exist_ok=True)

    if num_workers is None:
        num_workers = cpu_count()

    # # Path to the training data
    # data_dir = Path(data_folder)
    # dataset_name = data_dir.name

    # # Create the binaries directory if it doesn't exist
    # binary_dir = Path(f"resources/drive/binaries/{dataset_name}")
    # binary_dir.mkdir(parents=True, exist_ok=True)

    # Get all JSON files in the training directory
    # json_files = sorted(data_dir.glob("*.json"))
    json_files = sorted(json_dir.rglob("*.json"))

    print(f"Found {len(json_files)} json files")

    # Prepare arguments for parallel processing
    tasks = []
    for i, map_path in enumerate(json_files[:max_maps]):
        binary_file = f"map_{i:06d}.bin"  # Use zero-padded numbers for consistent sorting
        binary_path = binary_dir / binary_file
        tasks.append((i, map_path, binary_path))

    # Process maps in parallel with progress bar
    with Pool(num_workers) as pool:
        results = list(
            tqdm(pool.imap(_process_single_map, tasks), total=len(tasks), desc="Processing maps", unit="map")
        )

    # Collect statistics
    successful = sum(1 for _, _, success, _ in results if success)
    failed = sum(1 for _, _, success, _ in results if not success)

    if failed > 0:
        print(f"\nFailed {failed}/{len(results)} files:")
        for i, name, success, error in results:
            if not success:
                print(f"  {name}: {error}")


def test_performance(timeout=10, atn_cache=1024, num_agents=1024):
    import time

    env = Drive(
        num_agents=num_agents,
        num_maps=1,
        control_mode="control_vehicles",
        init_mode="create_all_valid",
        init_steps=0,
        episode_length=91,
    )

    env.reset()

    tick = 0
    actions = np.stack(
        [np.random.randint(0, space.n + 1, (atn_cache, num_agents)) for space in env.single_action_space], axis=-1
    )

    start = time.time()
    while time.time() - start < timeout:
        atn = actions[tick % atn_cache]
        env.step(atn)
        tick += 1

    print(f"SPS: {num_agents * tick / (time.time() - start)}")

    env.close()


if __name__ == "__main__":
    # test_performance()
    # process_all_maps()
    for split in ("training", "validation", "testing"):
        cur_bin_dir = Path(os.path.join(os.environ['DRIVE_BINARIES_DATA_ROOT'], split))
        cur_json_dir = Path(os.path.join(os.environ['DRIVE_DATA_ROOT'], split))
        process_all_maps(cur_json_dir, cur_bin_dir,max_maps=10_000_000)
