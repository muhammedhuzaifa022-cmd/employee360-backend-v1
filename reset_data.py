from app.db.session import SessionLocal
from sqlalchemy import text

def reset_transactional_data():
    db = SessionLocal()
    try:
        print("Wiping all tasks, leaves, attendance, and reports...")
        
        # Delete data in order (children first to avoid foreign key errors)
        db.execute(text("DELETE FROM task_comments"))
        db.execute(text("DELETE FROM task_history"))
        db.execute(text("DELETE FROM tasks"))
        db.execute(text("DELETE FROM leave_requests"))
        db.execute(text("DELETE FROM attendance"))
        db.execute(text("DELETE FROM daily_reports"))
        db.execute(text("DELETE FROM notifications"))
        db.execute(text("DELETE FROM projects")) 
        
        db.commit()
        print("✅ All test data deleted successfully!")
        print("Your users and departments are safe.")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    reset_transactional_data()