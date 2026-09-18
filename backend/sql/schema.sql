-- 由 scripts/dump_schema.py 自动生成，请勿手工编辑。
-- 权威定义在 app/models.py。

CREATE TABLE operators (
	id BIGSERIAL NOT NULL, 
	username VARCHAR(64) NOT NULL, 
	display_name VARCHAR(64), 
	role VARCHAR(24) NOT NULL, 
	password_hash VARCHAR(255), 
	active BOOLEAN NOT NULL, 
	last_login_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (username)
);

CREATE TABLE pens (
	id BIGSERIAL NOT NULL, 
	pen_code VARCHAR(64) NOT NULL, 
	pen_name VARCHAR(128), 
	barn VARCHAR(64), 
	area_name VARCHAR(128), 
	capacity INTEGER, 
	guardrail_camera_code VARCHAR(64), 
	arm_camera_code VARCHAR(64), 
	arm_device_code VARCHAR(64), 
	status VARCHAR(24) NOT NULL, 
	remark TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (pen_code)
);

CREATE TABLE system_events (
	id BIGSERIAL NOT NULL, 
	event_type VARCHAR(48) NOT NULL, 
	level VARCHAR(16) NOT NULL, 
	source VARCHAR(64), 
	message TEXT, 
	detail JSONB, 
	occurred_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_system_events_time ON system_events (occurred_at);

CREATE TABLE devices (
	id BIGSERIAL NOT NULL, 
	device_code VARCHAR(64) NOT NULL, 
	device_type VARCHAR(32) NOT NULL, 
	vendor VARCHAR(64), 
	model VARCHAR(64), 
	serial_number VARCHAR(128), 
	firmware_version VARCHAR(64), 
	protocol VARCHAR(32), 
	endpoint VARCHAR(255), 
	mounted_on VARCHAR(32), 
	pen_id BIGINT, 
	installed_at TIMESTAMP WITH TIME ZONE, 
	status VARCHAR(24) NOT NULL, 
	last_seen_at TIMESTAMP WITH TIME ZONE, 
	remark TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (device_code), 
	FOREIGN KEY(pen_id) REFERENCES pens (id) ON DELETE SET NULL
);

CREATE TABLE pigs (
	id BIGSERIAL NOT NULL, 
	ear_tag VARCHAR(64), 
	pen_id BIGINT, 
	breed VARCHAR(64), 
	sex VARCHAR(16), 
	birth_date DATE, 
	weight_kg NUMERIC(6, 2), 
	health_status VARCHAR(24) NOT NULL, 
	last_injection_at TIMESTAMP WITH TIME ZONE, 
	remark TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (ear_tag), 
	FOREIGN KEY(pen_id) REFERENCES pens (id) ON DELETE SET NULL
);

CREATE TABLE arm_status_samples (
	id BIGSERIAL NOT NULL, 
	device_id BIGINT NOT NULL, 
	control_mode VARCHAR(24) NOT NULL, 
	servo_power_on BOOLEAN, 
	estop_pressed BOOLEAN, 
	is_moving BOOLEAN, 
	motion_done BOOLEAN, 
	speed_override_pct NUMERIC(5, 2), 
	safety_state VARCHAR(32), 
	joint_angles_deg JSONB, 
	joint_velocities JSONB, 
	joint_torques JSONB, 
	joint_currents_a JSONB, 
	joint_temps_c JSONB, 
	tcp_pose JSONB, 
	tcp_quaternion JSONB, 
	tcp_linear_velocity JSONB, 
	tcp_force JSONB, 
	tool_frame VARCHAR(32), 
	base_frame VARCHAR(32), 
	payload_kg NUMERIC(6, 3), 
	obstacle_avoidance_enabled BOOLEAN, 
	obstacle_distance_mm NUMERIC(8, 2), 
	error_code VARCHAR(64), 
	error_message TEXT, 
	warning_codes JSONB, 
	queue_len INTEGER, 
	active_command_id UUID, 
	raw JSONB, 
	sampled_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE CASCADE
);
CREATE INDEX ix_arm_status_device_time ON arm_status_samples (device_id, sampled_at);
CREATE INDEX ix_arm_status_sampled_at ON arm_status_samples (sampled_at);

CREATE TABLE control_commands (
	id BIGSERIAL NOT NULL, 
	request_id UUID NOT NULL, 
	device_id BIGINT NOT NULL, 
	operator_id BIGINT, 
	task_id BIGINT, 
	command_type VARCHAR(48) NOT NULL, 
	source VARCHAR(24) NOT NULL, 
	client_ip VARCHAR(64), 
	payload JSONB, 
	result VARCHAR(24) NOT NULL, 
	accepted BOOLEAN, 
	reject_reason TEXT, 
	arm_command_id VARCHAR(128), 
	error_code VARCHAR(64), 
	response JSONB, 
	duration_ms INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (request_id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE CASCADE, 
	FOREIGN KEY(operator_id) REFERENCES operators (id) ON DELETE SET NULL
);
CREATE INDEX ix_control_commands_device_time ON control_commands (device_id, created_at);
CREATE INDEX ix_control_commands_type_time ON control_commands (command_type, created_at);

CREATE TABLE device_heartbeats (
	id BIGSERIAL NOT NULL, 
	device_id BIGINT NOT NULL, 
	online BOOLEAN NOT NULL, 
	latency_ms INTEGER, 
	firmware_version VARCHAR(64), 
	controller_temp_c NUMERIC(5, 2), 
	uptime_s BIGINT, 
	error_code VARCHAR(64), 
	error_message TEXT, 
	raw JSONB, 
	sampled_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE CASCADE
);
CREATE INDEX ix_device_heartbeats_device_time ON device_heartbeats (device_id, sampled_at);

CREATE TABLE injection_tasks (
	id BIGSERIAL NOT NULL, 
	task_no VARCHAR(64) NOT NULL, 
	batch_no VARCHAR(64), 
	device_id BIGINT NOT NULL, 
	pen_id BIGINT, 
	pig_id BIGINT, 
	ear_tag_snapshot VARCHAR(64), 
	operator_id BIGINT, 
	operator_name VARCHAR(64), 
	mode VARCHAR(24) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	fail_reason VARCHAR(64), 
	fail_message TEXT, 
	target_source VARCHAR(32), 
	target_point_base JSONB, 
	target_point_pixel JSONB, 
	target_confidence NUMERIC(5, 4), 
	target_depth_mm NUMERIC(6, 2), 
	target_angle_deg NUMERIC(6, 2), 
	actual_entry_point JSONB, 
	actual_depth_mm NUMERIC(6, 2), 
	actual_angle_deg NUMERIC(6, 2), 
	position_error_mm NUMERIC(6, 2), 
	needle_id VARCHAR(64), 
	drug_name VARCHAR(128), 
	drug_batch_no VARCHAR(64), 
	dose_ml NUMERIC(6, 3), 
	dose_target_ml NUMERIC(6, 3), 
	peak_force_n NUMERIC(6, 3), 
	peak_torque_nm NUMERIC(6, 3), 
	body_temp_c NUMERIC(5, 2), 
	ambient_temp_c NUMERIC(5, 2), 
	started_at TIMESTAMP WITH TIME ZONE, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	duration_ms INTEGER, 
	phase_durations_ms JSONB, 
	obstacle_triggered BOOLEAN NOT NULL, 
	retry_count INTEGER NOT NULL, 
	raw JSONB, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_injection_tasks_dose_nonnegative CHECK (dose_ml IS NULL OR dose_ml >= 0), 
	UNIQUE (task_no), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE RESTRICT, 
	FOREIGN KEY(pen_id) REFERENCES pens (id) ON DELETE SET NULL, 
	FOREIGN KEY(pig_id) REFERENCES pigs (id) ON DELETE SET NULL, 
	FOREIGN KEY(operator_id) REFERENCES operators (id) ON DELETE SET NULL
);
CREATE INDEX ix_injection_tasks_pig_time ON injection_tasks (pig_id, created_at);
CREATE INDEX ix_injection_tasks_status_time ON injection_tasks (status, created_at);

CREATE TABLE manual_control_sessions (
	id BIGSERIAL NOT NULL, 
	session_id UUID NOT NULL, 
	device_id BIGINT NOT NULL, 
	operator_id BIGINT, 
	operator_name VARCHAR(64), 
	client_ip VARCHAR(64), 
	started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	ended_at TIMESTAMP WITH TIME ZONE, 
	end_reason VARCHAR(32), 
	jog_command_count INTEGER NOT NULL, 
	max_speed_pct NUMERIC(5, 2), 
	estop_triggered BOOLEAN NOT NULL, 
	remark TEXT, 
	PRIMARY KEY (id), 
	UNIQUE (session_id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE CASCADE, 
	FOREIGN KEY(operator_id) REFERENCES operators (id) ON DELETE SET NULL
);

CREATE TABLE alarms (
	id BIGSERIAL NOT NULL, 
	alarm_no VARCHAR(64) NOT NULL, 
	device_id BIGINT, 
	task_id BIGINT, 
	level VARCHAR(16) NOT NULL, 
	category VARCHAR(48) NOT NULL, 
	code VARCHAR(64), 
	title VARCHAR(128) NOT NULL, 
	message TEXT, 
	value NUMERIC(12, 4), 
	threshold NUMERIC(12, 4), 
	status VARCHAR(16) NOT NULL, 
	acknowledged_by BIGINT, 
	acknowledged_at TIMESTAMP WITH TIME ZONE, 
	cleared_at TIMESTAMP WITH TIME ZONE, 
	asset_id BIGINT, 
	raw JSONB, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_alarms_alarm_no UNIQUE (alarm_no), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE SET NULL, 
	FOREIGN KEY(task_id) REFERENCES injection_tasks (id) ON DELETE SET NULL, 
	FOREIGN KEY(acknowledged_by) REFERENCES operators (id) ON DELETE SET NULL
);
CREATE INDEX ix_alarms_level_time ON alarms (level, created_at);
CREATE INDEX ix_alarms_status_time ON alarms (status, created_at);

CREATE TABLE injection_events (
	id BIGSERIAL NOT NULL, 
	task_id BIGINT NOT NULL, 
	event_type VARCHAR(48) NOT NULL, 
	phase VARCHAR(24), 
	message TEXT, 
	payload JSONB, 
	occurred_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES injection_tasks (id) ON DELETE CASCADE
);
CREATE INDEX ix_injection_events_task_time ON injection_events (task_id, occurred_at);

CREATE TABLE media_assets (
	id BIGSERIAL NOT NULL, 
	asset_type VARCHAR(24) NOT NULL, 
	category VARCHAR(48) NOT NULL, 
	task_id BIGINT, 
	device_id BIGINT, 
	file_path VARCHAR(512) NOT NULL, 
	file_name VARCHAR(255) NOT NULL, 
	mime_type VARCHAR(64), 
	file_size_bytes BIGINT, 
	width INTEGER, 
	height INTEGER, 
	duration_ms INTEGER, 
	checksum_sha256 VARCHAR(64), 
	captured_at TIMESTAMP WITH TIME ZONE, 
	remark TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES injection_tasks (id) ON DELETE SET NULL, 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE SET NULL
);
CREATE INDEX ix_media_assets_category_time ON media_assets (category, captured_at);

CREATE TABLE obstacle_events (
	id BIGSERIAL NOT NULL, 
	device_id BIGINT, 
	task_id BIGINT, 
	event_type VARCHAR(32) NOT NULL, 
	sensor_type VARCHAR(32), 
	obstacle_distance_mm NUMERIC(8, 2), 
	obstacle_direction VARCHAR(24), 
	obstacle_position JSONB, 
	obstacle_bbox JSONB, 
	obstacle_class VARCHAR(48), 
	detection_confidence NUMERIC(5, 4), 
	point_cloud_asset_id BIGINT, 
	action_taken VARCHAR(32), 
	speed_before_pct NUMERIC(5, 2), 
	speed_after_pct NUMERIC(5, 2), 
	resumed BOOLEAN, 
	detected_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	cleared_at TIMESTAMP WITH TIME ZONE, 
	duration_ms INTEGER, 
	raw JSONB, 
	PRIMARY KEY (id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE SET NULL, 
	FOREIGN KEY(task_id) REFERENCES injection_tasks (id) ON DELETE SET NULL
);
CREATE INDEX ix_obstacle_events_device_time ON obstacle_events (device_id, detected_at);

CREATE TABLE thermal_captures (
	id BIGSERIAL NOT NULL, 
	device_id BIGINT, 
	task_id BIGINT, 
	capture_no VARCHAR(64), 
	frame_seq BIGINT, 
	emissivity NUMERIC(4, 2), 
	distance_m NUMERIC(5, 2), 
	reflected_temp_c NUMERIC(5, 2), 
	atmospheric_temp_c NUMERIC(5, 2), 
	humidity_pct NUMERIC(5, 2), 
	temp_range_min_c NUMERIC(5, 2), 
	temp_range_max_c NUMERIC(5, 2), 
	temp_max_c NUMERIC(5, 2), 
	temp_min_c NUMERIC(5, 2), 
	temp_avg_c NUMERIC(5, 2), 
	temp_center_c NUMERIC(5, 2), 
	matrix_width INTEGER, 
	matrix_height INTEGER, 
	body_temp_c NUMERIC(5, 2), 
	injected_site_temp_c NUMERIC(5, 2), 
	ambient_temp_c NUMERIC(5, 2), 
	is_fever BOOLEAN, 
	thermal_asset_id BIGINT, 
	visible_asset_id BIGINT, 
	raw_asset_id BIGINT, 
	raw JSONB, 
	captured_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE SET NULL, 
	FOREIGN KEY(task_id) REFERENCES injection_tasks (id) ON DELETE CASCADE
);
CREATE INDEX ix_thermal_captures_device_time ON thermal_captures (device_id, captured_at);
CREATE INDEX ix_thermal_captures_task ON thermal_captures (task_id);

CREATE TABLE vision_detections (
	id BIGSERIAL NOT NULL, 
	device_id BIGINT, 
	camera_role VARCHAR(24) NOT NULL, 
	task_id BIGINT, 
	frame_seq BIGINT, 
	class_name VARCHAR(48) NOT NULL, 
	detected BOOLEAN NOT NULL, 
	confidence NUMERIC(5, 4), 
	pig_id BIGINT, 
	track_id VARCHAR(64), 
	bbox JSONB, 
	keypoints JSONB, 
	injection_point_pixel JSONB, 
	distance_mm NUMERIC(8, 2), 
	image_asset_id BIGINT, 
	raw JSONB, 
	captured_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE SET NULL, 
	FOREIGN KEY(task_id) REFERENCES injection_tasks (id) ON DELETE CASCADE, 
	FOREIGN KEY(pig_id) REFERENCES pigs (id) ON DELETE SET NULL
);
CREATE INDEX ix_vision_detections_device_time ON vision_detections (device_id, captured_at);
CREATE INDEX ix_vision_detections_task ON vision_detections (task_id);

CREATE TABLE thermal_rois (
	id BIGSERIAL NOT NULL, 
	thermal_capture_id BIGINT NOT NULL, 
	roi_name VARCHAR(64) NOT NULL, 
	shape VARCHAR(16), 
	geometry JSONB, 
	temp_max_c NUMERIC(5, 2), 
	temp_min_c NUMERIC(5, 2), 
	temp_avg_c NUMERIC(5, 2), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(thermal_capture_id) REFERENCES thermal_captures (id) ON DELETE CASCADE
);
