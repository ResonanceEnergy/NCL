#!/usr/bin/env python3
"""
CPU Task Manager Integration Demo
Demonstrates the CPU regulator and task manager working with the monitoring dashboard
"""

import time
import json
import subprocess
import sys
from pathlib import Path
from cpu_task_manager import CPUAndTaskManager, TaskPriority

def demo_task(name: str, duration: int = 5):
    """Demo task that simulates work"""
    print(f"Starting demo task: {name}")
    time.sleep(duration)
    print(f"Completed demo task: {name}")
    return f"Task {name} completed successfully"

def cpu_intensive_task(name: str):
    """CPU intensive demo task"""
    print(f"Starting CPU intensive task: {name}")
    result = 0
    for i in range(10000000):  # CPU intensive loop
        result += i ** 2
    print(f"Completed CPU intensive task: {name}")
    return result

def memory_intensive_task(name: str):
    """Memory intensive demo task"""
    print(f"Starting memory intensive task: {name}")
    data = []
    for i in range(100000):  # Create memory pressure
        data.append([i] * 100)
    time.sleep(2)
    print(f"Completed memory intensive task: {name}")
    return len(data)

def run_monitoring_dashboard():
    """Run the monitoring dashboard"""
    try:
        result = subprocess.run(
            [sys.executable, "advanced_monitoring_dashboard.py"],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False

def integration_demo():
    """Run the full integration demo"""
    print("🚀 Super Agency CPU & Task Manager Integration Demo")
    print("=" * 60)

    # Initialize the CPU and Task Manager
    manager = CPUAndTaskManager()

    # Start the manager
    print("📈 Starting CPU Regulator & Task Manager...")
    manager.start()

    # Wait for initialization
    time.sleep(2)

    # Display initial status
    print("\n📊 Initial Status:")
    manager.display_dashboard()

    # Add demo tasks with different priorities
    print("\n🎯 Adding Demo Tasks...")

    # Critical priority task
    task1_id = manager.add_task(
        "Critical Monitoring Task",
        TaskPriority.CRITICAL,
        demo_task,
        "Critical Monitor",
        3
    )

    # High priority CPU intensive task
    task2_id = manager.add_task(
        "High Priority CPU Task",
        TaskPriority.HIGH,
        cpu_intensive_task,
        "CPU Worker 1"
    )

    # Normal priority tasks
    task3_id = manager.add_task(
        "Normal Priority Task 1",
        TaskPriority.NORMAL,
        demo_task,
        "Normal Task 1",
        2
    )

    task4_id = manager.add_task(
        "Normal Priority Task 2",
        TaskPriority.NORMAL,
        demo_task,
        "Normal Task 2",
        2
    )

    # Low priority memory intensive task
    task5_id = manager.add_task(
        "Low Priority Memory Task",
        TaskPriority.LOW,
        memory_intensive_task,
        "Memory Worker"
    )

    # Background monitoring task
    task6_id = manager.add_task(
        "Background Dashboard Task",
        TaskPriority.BACKGROUND,
        run_monitoring_dashboard
    )

    print(f"✅ Added {6} demo tasks")

    # Monitor progress
    print("\n⏳ Monitoring Task Execution...")
    start_time = time.time()

    while time.time() - start_time < 30:  # Run for 30 seconds
        time.sleep(5)

        # Display current status
        print(f"\n📈 Status Update ({int(time.time() - start_time)}s elapsed):")
        status = manager.get_status()

        tm_status = status["task_manager"]
        print(f"   Running: {tm_status['running_tasks']} | Completed: {tm_status['completed_tasks']} | Failed: {tm_status['failed_tasks']}")

        # Show CPU regulator status
        cpu_status = status["cpu_regulator"]
        print(f"   CPU: {cpu_status['current_cpu']:.1f}% | Memory: {cpu_status['current_memory']:.1f}% | Throttled: {cpu_status['throttled_processes']}")

        # Check if all tasks are done
        if tm_status['running_tasks'] == 0 and tm_status['queued_tasks'] == 0:
            break

    # Final status
    print("\n🏁 Final Results:")
    manager.display_dashboard()

    # Show task details
    print("\n📋 Task Details:")
    all_tasks = [task1_id, task2_id, task3_id, task4_id, task5_id, task6_id]
    for task_id in all_tasks:
        task_status = manager.task_manager.get_task_status(task_id)
        if task_status:
            status_emoji = {
                "completed": "✅",
                "running": "🔄",
                "failed": "❌",
                "pending": "⏳",
                "cancelled": "🚫"
            }.get(task_status["status"], "❓")

            print(f"   {status_emoji} {task_status['name']}: {task_status['status']}")

    # Stop the manager
    print("\n🛑 Stopping CPU Regulator & Task Manager...")
    manager.stop()

    print("\n🎉 Integration Demo Complete!")
    print("\n💡 Key Features Demonstrated:")
    print("   • CPU regulation with automatic throttling")
    print("   • Priority-based task scheduling")
    print("   • Resource limit enforcement")
    print("   • Concurrent task execution")
    print("   • Real-time monitoring and status updates")

def quick_start():
    """Quick start function for immediate use"""
    print("🚀 Quick Start: CPU & Task Manager")
    print("=" * 40)

    manager = CPUAndTaskManager()
    manager.start()

    print("✅ CPU Regulator & Task Manager started")
    print("💡 Use the dashboard command to monitor:")
    print("   python cpu_task_manager.py dashboard")

    # Add a simple monitoring task
    manager.add_task(
        "System Health Check",
        TaskPriority.NORMAL,
        lambda: print("🔍 System health check completed")
    )

    try:
        while True:
            time.sleep(10)
            # Display brief status every 10 seconds
            status = manager.get_status()
            cpu = status["cpu_regulator"]
            tm = status["task_manager"]
            print(f"📊 CPU: {cpu['current_cpu']:.1f}% | Tasks: {tm['running_tasks']} running, {tm['completed_tasks']} completed")
    except KeyboardInterrupt:
        print("\n⚠️  Stopping...")
        manager.stop()
        print("✅ Stopped")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "quick":
        quick_start()
    else:
        integration_demo()