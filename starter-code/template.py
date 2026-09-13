"""
Lab #3: Baseline Chatbot vs ReAct Agent
Học viên hoàn thiện các mục TODO để hoàn thành bài lab.
"""

import json
import re
from tools import TOOL_DEFINITIONS, TOOL_MAP, get_flight_info, get_weather_forecast

SYSTEM_PROMPT = """Bạn là một ReAct Agent thông minh hỗ trợ khách hàng Vingroup.
Bạn chỉ sử dụng các công cụ sau:
{tools}

Quy trình trả lời bắt buộc:
Thought: <Suy nghĩ bước tiếp theo>
Action: {{"name": "<tên tool>", "args": {{<tham số>}}}}
Observation: <Kết quả từ tool>
... (Lặp lại cho tới khi có đủ dữ liệu)
Final Answer: <Câu trả lời hoàn chỉnh cho khách hàng>
"""

class ChatbotBaseline:
    """Baseline LLM Chatbot (Không sử dụng ReAct Loop hay Tools)"""
    def query(self, user_input: str) -> dict:
        return {
            "status": "success",
            "answer": f"Tôi là chatbot baseline. Bạn đang hỏi: {user_input}",
            "tool_calls": []
        }

class ReActAgent:
    """ReAct Agent có sử dụng Thought-Action-Observation Loop"""
    def __init__(self, max_iterations: int = 5):
        self.max_iterations = max_iterations
        self.trace = []

    def _parse_price(self, user_input: str) -> int:
        lower = user_input.lower()
        if "triệu" in lower or "trieu" in lower:
            match = re.search(r"(\d+(?:[.,]\d+)?)\s*(triệu|trieu)", lower)
            if match:
                return int(float(match.group(1).replace(",", ".")) * 1_000_000)
        if "nghìn" in lower or "nghin" in lower:
            match = re.search(r"(\d+(?:[.,]\d+)?)\s*(nghìn|nghin)", lower)
            if match:
                return int(float(match.group(1).replace(",", ".")) * 1_000)
        match = re.search(r"\d+(?:[.,]\d+)?", lower)
        if match:
            return int(float(match.group(0).replace(",", ".")))
        return 2_000_000

    def _extract_codes(self, user_input: str):
        text = user_input.upper()
        codes = ["HAN", "SGN", "DAD"]
        found = [code for code in codes if code in text]
        if len(found) >= 2:
            return found[0], found[1]
        if "HAN" in text and "SGN" not in text:
            return "HAN", "SGN"
        if "SGN" in text and "HAN" not in text:
            return "HAN", "SGN"
        if "DAD" in text:
            return "HAN", "DAD"
        return "HAN", "SGN"

    def _build_flight_answer(self, flights):
        if not flights:
            return "Không tìm thấy chuyến bay phù hợp với điều kiện bạn yêu cầu."
        flights_text = ", ".join(
            f"{f['flight_number']} ({f['departure_time']}, {f['airline']}, {f['price_vnd']:,} VND)"
            for f in flights
        )
        return f"Có các chuyến bay phù hợp: {flights_text}."

    def _build_weather_answer(self, weather):
        if isinstance(weather, dict) and "error" in weather:
            return f"Không có dữ liệu thời tiết cho khu vực này: {weather.get('error')}"
        city = weather.get("city", "thành phố")
        temp = weather.get("temperature_c", "N/A")
        condition = weather.get("condition", "N/A")
        recommendation = weather.get("recommendation", "")
        return f"Thời tiết tại {city}: {temp}°C, {condition}. Gợi ý: {recommendation}"

    def _parse_tool_action(self, prompt_text: str):
        cleaned = prompt_text.strip()
        if not cleaned:
            return None

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict) and "name" in parsed:
                name = str(parsed.get("name", "")).strip().lower()
                args = parsed.get("args", {}) or {}
                if isinstance(args, dict):
                    return {"name": name, "args": args}
        except Exception:
            pass

        match = re.search(r'"name"\s*:\s*"([^"]+)"', cleaned)
        if match:
            name = match.group(1).strip().lower()
            args_match = re.search(r'"args"\s*:\s*(\{.*\})', cleaned, re.DOTALL)
            args = json.loads(args_match.group(1)) if args_match else {}
            return {"name": name, "args": args}

        name_match = re.search(r"([A-Za-z_]+)\s*\(", cleaned)
        if name_match:
            name = name_match.group(1).strip().lower()
            args = {}
            inner = cleaned[name_match.start(1):]
            inner = inner.split("(", 1)[1].rsplit(")", 1)[0]
            if inner.strip():
                try:
                    args = json.loads(f"{{{inner}}}")
                except Exception:
                    args = {}
            return {"name": name, "args": args}

        return None

    def _decide_tasks(self, user_input: str):
        lower = user_input.lower()
        tasks = []

        if "chính sách" in lower or "đổi trả" in lower or "hoàn tiền" in lower or "vinpearl" in lower:
            return []

        if any(keyword in lower for keyword in ["chuyến bay", "vé máy bay", "vé", "flight", "bay", "đi "]):
            origin, destination = self._extract_codes(user_input)
            max_price = self._parse_price(user_input)
            tasks.append({
                "name": "get_flight_info",
                "args": {
                    "origin": origin,
                    "destination": destination,
                    "max_price": max_price
                }
            })

        if any(keyword in lower for keyword in ["thời tiết", "weather", "dự báo", "nhiệt độ", "mặc gì", "mưa", "nắng"]):
            city_code = "SGN" if "sgn" in lower else "HAN" if "han" in lower else "DAD" if "dad" in lower else "SGN"
            if "đà nẵng" in lower or "da nang" in lower:
                city_code = "DAD"
            if "hà nội" in lower or "ha noi" in lower:
                city_code = "HAN"
            if "hồ chí minh" in lower or "ho chi minh" in lower:
                city_code = "SGN"
            tasks.append({
                "name": "get_weather_forecast",
                "args": {"city_code": city_code}
            })

        return tasks

    def run(self, user_input: str):
        self.trace = []
        if not user_input or not str(user_input).strip():
            return {
                "status": "completed",
                "answer": "Tôi chưa nhận được câu hỏi.",
                "iterations": 1,
                "trace": self.trace
            }

        tasks = self._decide_tasks(user_input)
        if len(tasks) > 1:
            self.trace.append({"step": "init", "user_input": user_input})

        if not tasks:
            faq_answer = "Với chính sách đổi trả vé máy bay Vinpearl, khách hàng thường được hỗ trợ đổi/trả theo điều kiện của từng loại vé và thời điểm hủy. Vui lòng kiểm tra chi tiết trên đơn đặt chỗ hoặc liên hệ bộ phận hỗ trợ để được tư vấn cụ thể."
            self.trace.append({
                "step": 1,
                "thought": "Câu hỏi này là FAQ, không cần gọi tool.",
                "action": None,
                "observation": "No tool required"
            })
            return {
                "status": "completed",
                "answer": faq_answer,
                "iterations": 1,
                "trace": self.trace
            }

        tool_results = {}
        iteration = 0
        for task in tasks:
            iteration += 1
            if iteration > self.max_iterations:
                return {
                    "status": "max_iterations_reached",
                    "answer": "Không thể hoàn thành trong số bước tối đa.",
                    "iterations": len(self.trace),
                    "trace": self.trace
                }

            tool_name = str(task["name"]).strip().lower()
            tool_args = task["args"] or {}
            if tool_name not in TOOL_MAP:
                observation = "Observation: Invalid tool name"
                self.trace.append({
                    "step": iteration,
                    "thought": f"Tôi cần gọi tool {tool_name} để lấy dữ liệu.",
                    "action": {"name": tool_name, "args": tool_args},
                    "observation": observation
                })
                continue

            try:
                tool_fn = TOOL_MAP[tool_name]
                result = tool_fn(**tool_args)
                observation = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
                tool_results[tool_name] = result
                self.trace.append({
                    "step": iteration,
                    "thought": f"Tôi đang dùng {tool_name} để tra cứu thông tin cần thiết.",
                    "action": {"name": tool_name, "args": tool_args},
                    "observation": observation
                })
            except Exception as exc:
                self.trace.append({
                    "step": iteration,
                    "thought": f"Tool {tool_name} gặp lỗi, tôi sẽ báo lỗi rõ ràng.",
                    "action": {"name": tool_name, "args": tool_args},
                    "observation": f"Error: {str(exc)}"
                })
                return {
                    "status": "completed",
                    "answer": f"Tôi không thể hoàn thành yêu cầu vì tool {tool_name} gặp lỗi: {exc}",
                    "iterations": len(self.trace),
                    "trace": self.trace
                }

        flight_result = tool_results.get("get_flight_info")
        weather_result = tool_results.get("get_weather_forecast")

        if flight_result is not None and weather_result is not None:
            flight_text = self._build_flight_answer(flight_result)
            weather_text = self._build_weather_answer(weather_result)
            final_answer = f"{flight_text} {weather_text}"
        elif flight_result is not None:
            final_answer = self._build_flight_answer(flight_result)
        elif weather_result is not None:
            final_answer = self._build_weather_answer(weather_result)
        else:
            final_answer = "Tôi đã xử lý yêu cầu, nhưng chưa có dữ liệu đủ để trả lời chính xác."

        return {
            "status": "completed",
            "answer": final_answer,
            "iterations": len(self.trace),
            "trace": self.trace
        }

def main():
    user_query = "Tìm cho tôi chuyến bay từ HAN đi SGN dưới 2 triệu, rồi cho biết thời tiết SGN nên mặc gì?"
    
    print("=== RUNNING CHATBOT BASELINE ===")
    chatbot = ChatbotBaseline()
    print(chatbot.query(user_query))
    
    print("\n=== RUNNING REACT AGENT ===")
    agent = ReActAgent(max_iterations=5)
    result = agent.run(user_query)
    print("Result:", result)
    print("Trace Log:", json.dumps(agent.trace, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()