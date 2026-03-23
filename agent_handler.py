#!/usr/bin/env python3
"""AgentCore handler for Envoy agent"""

import json
import os
from service import EnvoyService

class EnvoyAgent:
    def __init__(self):
        self.service = EnvoyService()
    
    def handle_request(self, request: dict) -> dict:
        """Handle AgentCore requests"""
        tool = request.get('tool')
        params = request.get('parameters', {})
        
        if tool == 'generate_digest':
            return self.generate_digest(params)
        else:
            return {
                'success': False,
                'error': f'Unknown tool: {tool}'
            }
    
    def generate_digest(self, params: dict) -> dict:
        """Generate digest for a manager"""
        try:
            manager_alias = params.get('manager_alias')
            days = params.get('days', 14)
            include_ai = params.get('include_ai_summary', True)
            email_result = params.get('email_result', False)
            
            if not manager_alias:
                return {
                    'success': False,
                    'error': 'manager_alias is required'
                }
            
            # Generate raw digest
            digest = self.service.generate_digest(manager_alias, days)
            
            # Add AI summary if requested
            if include_ai:
                final_output = self.service.generate_ai_summary(digest, manager_alias, days)
            else:
                final_output = digest
            
            # Email if requested
            email_sent = False
            if email_result:
                email_sent = self.service.email_digest(
                    final_output, 
                    manager_alias, 
                    days, 
                    include_summary=include_ai
                )
            
            return {
                'success': True,
                'digest': final_output,
                'email_sent': email_sent,
                'manager': manager_alias,
                'days': days,
                'ai_summary_included': include_ai
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

# AgentCore entry point
def handler(event, context):
    """Lambda-style handler for AgentCore"""
    agent = EnvoyAgent()
    return agent.handle_request(event)

if __name__ == '__main__':
    # Test locally
    test_request = {
        'tool': 'generate_digest',
        'parameters': {
            'manager_alias': os.environ.get('USER', 'your-alias'),
            'days': 7,
            'include_ai_summary': True,
            'email_result': False
        }
    }
    
    result = handler(test_request, None)
    print(json.dumps(result, indent=2))
