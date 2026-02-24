"""
Chat Analytics for Mai Monitor
Analyze chat logs to extract insights
"""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

def load_chat_log(log_file="jsons/logs/history/chat_log.json"):
    """Load chat log as list of messages"""
    messages = []
    
    if not Path(log_file).exists():
        return messages
    
    with open(log_file, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                messages.append(json.loads(line))
            except:
                pass
    
    return messages

def analyze_activity(messages):
    """Analyze chat activity"""
    
    # Most active users
    user_counts = Counter(msg['username'] for msg in messages)
    
    # Message timeline
    times = [datetime.fromtimestamp(msg['timestamp']) for msg in messages]
    
    # Total messages
    total = len(messages)
    
    return {
        'total_messages': total,
        'unique_users': len(user_counts),
        'most_active': user_counts.most_common(10),
        'first_message': min(times) if times else None,
        'last_message': max(times) if times else None,
    }

def find_highlights(messages):
    """Find potential highlight moments based on chat reactions"""
    
    excitement_words = [
        'lol', 'lmao', 'omg', 'wow', 'holy', 'insane',
        'crazy', 'wtf', 'amazing', 'perfect', 'clutch'
    ]
    
    highlights = []
    
    for msg in messages:
        text = msg['message'].lower()
        
        # Count excitement indicators
        excitement_count = sum(1 for word in excitement_words if word in text)
        
        if excitement_count > 0 or '!' in msg['message']:
            highlights.append({
                'username': msg['username'],
                'message': msg['message'],
                'time': datetime.fromtimestamp(msg['timestamp']),
                'excitement_score': excitement_count
            })
    
    # Sort by excitement
    highlights.sort(key=lambda x: x['excitement_score'], reverse=True)
    
    return highlights[:20]  # Top 20

def print_summary(log_file="jsons/logs/history/chat_log.json"):
    """Print chat analytics summary"""
    
    messages = load_chat_log(log_file)
    
    if not messages:
        print("No chat log found or empty")
        return
    
    stats = analyze_activity(messages)
    highlights = find_highlights(messages)
    
    print("=" * 60)
    print("CHAT ANALYTICS SUMMARY")
    print("=" * 60)
    
    print(f"\nTotal Messages: {stats['total_messages']}")
    print(f"Unique Users: {stats['unique_users']}")
    print(f"Stream Duration: {stats['first_message']} to {stats['last_message']}")
    
    print(f"\nMost Active Users:")
    for username, count in stats['most_active'][:5]:
        print(f"  {username}: {count} messages")
    
    print(f"\nPotential Highlights (top 10):")
    for i, highlight in enumerate(highlights[:10], 1):
        time_str = highlight['time'].strftime('%H:%M:%S')
        print(f"  {i}. [{time_str}] {highlight['username']}: {highlight['message']}")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    print_summary()
