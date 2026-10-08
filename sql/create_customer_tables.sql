-- 智能客服多Agent系统 - 建表语句
-- 数据库: agent客服

USE `agent客服`;

-- 1. 订单表
DROP TABLE IF EXISTS orders;
CREATE TABLE orders (
    order_id VARCHAR(32) PRIMARY KEY COMMENT '订单号',
    user_id VARCHAR(32) COMMENT '用户ID',
    product_name VARCHAR(128) COMMENT '商品名称',
    status VARCHAR(32) COMMENT '订单状态：待付款/待发货/已发货/已完成/退款中/已退款',
    amount DECIMAL(10,2) COMMENT '订单金额',
    create_time DATETIME COMMENT '下单时间'
) ENGINE=INNODB DEFAULT CHARSET=utf8mb4 COMMENT='订单表';

-- 2. 物流表
DROP TABLE IF EXISTS logistics;
CREATE TABLE logistics (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    order_id VARCHAR(32) COMMENT '订单号',
    company VARCHAR(64) COMMENT '快递公司',
    tracking_no VARCHAR(64) COMMENT '运单号',
    status VARCHAR(64) COMMENT '物流状态：已揽收/运输中/派送中/已签收',
    update_time DATETIME COMMENT '更新时间'
) ENGINE=INNODB DEFAULT CHARSET=utf8mb4 COMMENT='物流信息表';

-- 3. 工单表
DROP TABLE IF EXISTS tickets;
CREATE TABLE tickets (
    ticket_id INT AUTO_INCREMENT PRIMARY KEY COMMENT '工单号',
    order_id VARCHAR(32) COMMENT '关联订单号',
    type VARCHAR(32) COMMENT '工单类型：退款/退货/换货/投诉/发票',
    description TEXT COMMENT '问题描述',
    status VARCHAR(32) COMMENT '工单状态：待处理/处理中/已解决/已关闭',
    assignee VARCHAR(64) COMMENT '处理人',
    create_time DATETIME COMMENT '创建时间'
) ENGINE=INNODB DEFAULT CHARSET=utf8mb4 COMMENT='售后工单表';

-- 插入测试数据
INSERT INTO orders VALUES
('ORD001', 'U1001', '无线蓝牙耳机', '已发货', 299.00, '2026-09-20 10:30:00'),
('ORD002', 'U1001', '手机透明壳', '待发货', 39.90, '2026-09-23 14:20:00'),
('ORD003', 'U1002', '充电宝20000mAh', '退款中', 129.00, '2026-09-18 09:15:00'),
('ORD004', 'U1003', '机械键盘', '已完成', 459.00, '2026-09-10 16:00:00'),
('ORD005', 'U1002', '数据线', '已发货', 19.90, '2026-09-22 11:00:00');

INSERT INTO logistics VALUES
(1, 'ORD001', '顺丰速运', 'SF1380001234', '运输中', '2026-09-24 08:30:00'),
(2, 'ORD005', '中通快递', 'ZT7788990011', '派送中', '2026-09-25 09:00:00'),
(3, 'ORD004', '京东物流', 'JD00998877', '已签收', '2026-09-12 15:20:00');

INSERT INTO tickets VALUES
(1, 'ORD003', '退款', '用户收到商品有划痕，申请全额退款', '待处理', '客服组A', '2026-09-24 10:00:00'),
(2, 'ORD004', '发票', '需要开具增值税普通发票', '已解决', '客服组B', '2026-09-15 11:00:00');
