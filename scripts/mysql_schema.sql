CREATE DATABASE IF NOT EXISTS aiword DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE aiword;

-- 用户表（页面2登录）
CREATE TABLE IF NOT EXISTS users (
    id CHAR(36) PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(128) NOT NULL,
    display_name VARCHAR(128),
    created_at DATETIME NOT NULL,
    updated_at DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 上传记录表（合并了任务分配功能）
CREATE TABLE IF NOT EXISTS upload_records (
    id CHAR(36) PRIMARY KEY,
    project_name VARCHAR(128) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    author VARCHAR(128) NOT NULL,
    stored_file_name VARCHAR(255),
    storage_path VARCHAR(512),
    original_file_name VARCHAR(255),
    template_links TEXT,
    placeholders JSON NULL,
    notes TEXT NULL,
    assignee_name VARCHAR(128),
    due_date DATE,
    task_status VARCHAR(32) DEFAULT 'pending',
    quick_completed TINYINT(1) DEFAULT 0,
    dingtalk_notified_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NULL,
    CONSTRAINT uq_project_file UNIQUE (project_name, file_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 生成记录表
CREATE TABLE IF NOT EXISTS generate_records (
    id CHAR(36) PRIMARY KEY,
    upload_id CHAR(36) NOT NULL,
    triggered_by VARCHAR(128),
    status VARCHAR(32) NOT NULL,
    success TINYINT(1) NOT NULL DEFAULT 0,
    placeholder_payload JSON NULL,
    output_file_name VARCHAR(255),
    output_path VARCHAR(512),
    created_at DATETIME NOT NULL,
    completed_at DATETIME NULL,
    CONSTRAINT fk_generate_upload FOREIGN KEY (upload_id) REFERENCES upload_records(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 生成统计汇总表
CREATE TABLE IF NOT EXISTS generation_summary (
    id CHAR(36) PRIMARY KEY,
    upload_id CHAR(36) NOT NULL UNIQUE,
    project_name VARCHAR(128) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    author VARCHAR(128) NOT NULL,
    total_generate_clicks INT NOT NULL DEFAULT 0,
    has_generated TINYINT(1) NOT NULL DEFAULT 0,
    last_generated_at DATETIME NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NULL,
    CONSTRAINT fk_summary_upload FOREIGN KEY (upload_id) REFERENCES upload_records(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
